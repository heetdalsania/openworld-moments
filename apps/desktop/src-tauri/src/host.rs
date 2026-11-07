// SPDX-License-Identifier: AGPL-3.0-or-later
//! Tauri integration for the worker supervisor: startup, UI events, commands, shutdown.

use std::path::PathBuf;
use std::time::Duration;

use serde_json::{Value, json};
use tauri::{AppHandle, Emitter, Manager, RunEvent, Runtime, State};

use crate::phone::{PhoneConfig, PhoneGateway};
use crate::watch::{WatchConfig, WatchService, WorkerSink};
use crate::worker::{SeqCheck, Supervisor, SupervisorConfig, WorkerCommand, WorkerStatus};

/// The watched-folder loop, present when a worker is configured.
pub type Watcher = Option<WatchService<WorkerSink>>;

/// UI event names.
pub const STATUS_EVENT: &str = "worker://status";
pub const JOB_EVENT: &str = "worker://job-event";
pub const RESYNC_EVENT: &str = "worker://resync";
pub const PHONE_EVENT: &str = "phone://status";

/// The phone import session manager, present when a worker is configured.
pub type Phone = Option<PhoneGateway>;

/// Where the worker comes from. `OWM_WORKER_PYTHON` overrides; debug builds fall
/// back to the repository's virtualenv. Packaged builds bundle a worker in M29.
fn worker_command() -> Option<WorkerCommand> {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let python = std::env::var_os("OWM_WORKER_PYTHON")
        .map(PathBuf::from)
        .or_else(|| {
            if !cfg!(debug_assertions) {
                return None;
            }
            let venv = if cfg!(windows) {
                ".venv/Scripts/python.exe"
            } else {
                ".venv/bin/python"
            };
            Some(repo.join(venv)).filter(|p| p.exists())
        })?;
    Some(WorkerCommand {
        program: python,
        args: vec!["-m".into(), "openworld_moments.worker".into()],
        cwd: Some(repo.join("services/media-worker")).filter(|p| p.exists()),
    })
}

pub fn setup<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    let Some(command) = worker_command() else {
        app.manage(None::<Supervisor>);
        app.manage(None::<WatchService<WorkerSink>> as Watcher);
        app.manage(None::<PhoneGateway> as Phone);
        return Ok(());
    };
    let library = app.path().app_data_dir()?.join("library");
    // No phone session runs yet: leftovers are from a crash.
    let phone_staging = library.join("staging").join("phone");
    crate::phone::clean_staging(&phone_staging);
    let phone = PhoneGateway::new(PhoneConfig {
        command: command.clone(),
        staging_root: phone_staging,
        session_seconds: crate::phone::SESSION_SECONDS,
        allow_loopback: false,
    });
    app.manage(Some(phone.clone()) as Phone);
    let handle = app.clone();
    let mut phone_changes = phone.subscribe();
    tauri::async_runtime::spawn(async move {
        while phone_changes.changed().await.is_ok() {
            let status = phone_changes.borrow_and_update().clone();
            let _ = handle.emit(PHONE_EVENT, &status);
        }
    });
    let supervisor = Supervisor::new(SupervisorConfig::new(command, library));
    app.manage(Some(supervisor.clone()));

    let watcher = WatchService::new(WorkerSink(supervisor.clone()), WatchConfig::default());
    app.manage(Some(watcher.clone()) as Watcher);
    tauri::async_runtime::spawn(watcher.clone().run());

    let handle = app.clone();
    let mut status = supervisor.subscribe_status();
    tauri::async_runtime::spawn(async move {
        loop {
            let current = status.borrow_and_update().clone();
            if matches!(current, WorkerStatus::Ready { .. }) {
                watcher.refresh(); // (re)load watched folders once the worker answers
            }
            let _ = handle.emit(STATUS_EVENT, &current);
            if status.changed().await.is_err() {
                break;
            }
        }
    });

    let relay = supervisor.clone();
    let handle = app.clone();
    tauri::async_runtime::spawn(async move { relay_events(handle, relay).await });

    tauri::async_runtime::spawn(async move {
        let _ = supervisor.start().await; // failures surface as WorkerStatus::Failed
    });
    Ok(())
}

async fn relay_events<R: Runtime>(app: AppHandle<R>, supervisor: Supervisor) {
    let mut status = supervisor.subscribe_status();
    loop {
        // Read into a bool so the watch guard is not held across the await below.
        let ready = matches!(*status.borrow_and_update(), WorkerStatus::Ready { .. });
        if ready && let Ok(mut stream) = supervisor.connect_events().await {
            // A new connection may have missed events: tell the UI to refresh.
            let _ = app.emit(RESYNC_EVENT, ());
            while let Some(item) = stream.next().await {
                match item {
                    Ok((event, SeqCheck::InOrder)) => {
                        let _ = app.emit(JOB_EVENT, &event.raw);
                    }
                    Ok((event, SeqCheck::Gap { .. })) => {
                        let _ = app.emit(RESYNC_EVENT, ());
                        let _ = app.emit(JOB_EVENT, &event.raw);
                    }
                    Ok((_, SeqCheck::Stale)) | Err(_) => {}
                }
            }
        }
        if status.changed().await.is_err() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

pub fn on_run_event<R: Runtime>(app: &AppHandle<R>, event: RunEvent) {
    if let RunEvent::Exit = event
        && let Some(phone) = app.try_state::<Phone>().and_then(|p| p.inner().clone())
    {
        tauri::async_runtime::block_on(phone.stop());
    }
    if let RunEvent::Exit = event
        && let Some(watcher) = app.try_state::<Watcher>().and_then(|w| w.inner().clone())
    {
        watcher.stop();
    }
    if let RunEvent::Exit = event
        && let Some(supervisor) = app
            .try_state::<Option<Supervisor>>()
            .and_then(|s| s.inner().clone())
    {
        tauri::async_runtime::block_on(supervisor.stop());
    }
}

fn unavailable() -> Value {
    json!({
        "status": "failed",
        "code": "worker.not_bundled",
        "message": "No worker is configured for this build. Set OWM_WORKER_PYTHON or run a debug build.",
        "stderr_tail": ""
    })
}

fn supervisor(state: &State<'_, Option<Supervisor>>) -> Result<Supervisor, Value> {
    state.inner().clone().ok_or_else(unavailable)
}

fn to_ui_error(err: crate::worker::SupervisorError) -> Value {
    match err {
        crate::worker::SupervisorError::Http { body, .. } => body,
        other => {
            json!({ "code": "worker.unavailable", "message": other.to_string(), "retryable": true })
        }
    }
}

#[tauri::command]
pub fn worker_status(state: State<'_, Option<Supervisor>>) -> Value {
    match state.inner() {
        Some(s) => serde_json::to_value(s.status()).unwrap_or_else(|_| unavailable()),
        None => unavailable(),
    }
}

#[tauri::command]
pub async fn worker_start_diagnostic(
    state: State<'_, Option<Supervisor>>,
    steps: u32,
    step_ms: u32,
) -> Result<Value, Value> {
    let supervisor = supervisor(&state)?;
    supervisor
        .submit_job(
            "diagnostic",
            json!({ "steps": steps, "step_ms": step_ms }),
            None,
        )
        .await
        .map_err(to_ui_error)
}

#[tauri::command]
pub async fn worker_cancel_job(
    state: State<'_, Option<Supervisor>>,
    job_id: String,
) -> Result<Value, Value> {
    supervisor(&state)?
        .cancel_job(&job_id)
        .await
        .map_err(to_ui_error)
}

/// The UI's general route to the worker (M09). Only routes in
/// [`crate::media::api_route_allowed`] pass; the token stays in the host.
#[tauri::command]
pub async fn worker_api(
    state: State<'_, Option<Supervisor>>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, Value> {
    if !crate::media::api_route_allowed(&method, &path) {
        return Err(crate::media::route_refused());
    }
    let method = match method.as_str() {
        "GET" => reqwest::Method::GET,
        "POST" => reqwest::Method::POST,
        "PUT" => reqwest::Method::PUT,
        _ => return Err(crate::media::route_refused()),
    };
    supervisor(&state)?
        .request(method, &path, body.as_ref(), None)
        .await
        .map_err(to_ui_error)
}

/// Answer one `owm-media://` request (see [`crate::media`]).
pub fn media_protocol<R: Runtime>(
    app: &AppHandle<R>,
    request: tauri::http::Request<Vec<u8>>,
    responder: tauri::UriSchemeResponder,
) {
    let supervisor = app
        .try_state::<Option<Supervisor>>()
        .and_then(|s| s.inner().clone());
    let path = request.uri().path().to_string();
    let range = request
        .headers()
        .get("range")
        .and_then(|v| v.to_str().ok())
        .map(str::to_string);
    tauri::async_runtime::spawn(async move {
        let response = match supervisor {
            Some(supervisor) => crate::media::serve(&supervisor, &path, range.as_deref()).await,
            None => crate::media::MediaResponse {
                status: 503,
                headers: vec![("Content-Type", "application/json".into())],
                body: unavailable().to_string().into_bytes(),
            },
        };
        let mut builder = tauri::http::Response::builder().status(response.status);
        for (name, value) in response.headers {
            builder = builder.header(name, value);
        }
        let reply = builder
            .body(response.body)
            .unwrap_or_else(|_| tauri::http::Response::new(Vec::new()));
        responder.respond(reply);
    });
}

#[tauri::command]
pub async fn worker_list_jobs(state: State<'_, Option<Supervisor>>) -> Result<Value, Value> {
    supervisor(&state)?.list_jobs().await.map_err(to_ui_error)
}

// -- import from phone (M10) ---------------------------------------------------------

fn phone(state: &State<'_, Phone>) -> Result<PhoneGateway, Value> {
    state.inner().clone().ok_or_else(unavailable)
}

/// Private network addresses a phone session may listen on.
#[tauri::command]
pub fn phone_interfaces() -> Vec<crate::phone::NetInterface> {
    crate::phone::private_interfaces()
}

#[tauri::command]
pub fn phone_status(state: State<'_, Phone>) -> Result<crate::phone::PhoneStatus, Value> {
    Ok(phone(&state)?.status())
}

/// Open the temporary upload page on `address` (0 = any free port).
#[tauri::command]
pub async fn phone_start(
    state: State<'_, Phone>,
    worker: State<'_, Option<Supervisor>>,
    address: String,
    port: Option<u16>,
) -> Result<crate::phone::PhoneStatus, Value> {
    let gateway = phone(&state)?;
    gateway
        .start(worker.inner().clone(), &address, port.unwrap_or(0))
        .await
}

/// Close the upload page now. Imports of files already received continue.
#[tauri::command]
pub async fn phone_stop(state: State<'_, Phone>) -> Result<crate::phone::PhoneStatus, Value> {
    let gateway = phone(&state)?;
    gateway.stop().await;
    Ok(gateway.status())
}

// -- watched folders (M07) -----------------------------------------------------------

fn refresh_watcher(watcher: &State<'_, Watcher>) {
    if let Some(w) = watcher.inner() {
        w.refresh();
    }
}

/// Folders from the worker plus the host's live status for each.
#[tauri::command]
pub async fn watched_folders_list(
    state: State<'_, Option<Supervisor>>,
    watcher: State<'_, Watcher>,
) -> Result<Value, Value> {
    let folders = supervisor(&state)?
        .request(reqwest::Method::GET, "/v1/watched-folders", None, None)
        .await
        .map_err(to_ui_error)?;
    let status = watcher
        .inner()
        .as_ref()
        .map(|w| w.status())
        .unwrap_or_default();
    Ok(json!({ "folders": folders, "status": status }))
}

#[tauri::command]
pub async fn watched_folder_add(
    state: State<'_, Option<Supervisor>>,
    watcher: State<'_, Watcher>,
    path: String,
    source_kind: String,
) -> Result<Value, Value> {
    let body = json!({ "path": path, "source_kind": source_kind });
    let created = supervisor(&state)?
        .request(
            reqwest::Method::POST,
            "/v1/watched-folders",
            Some(&body),
            None,
        )
        .await
        .map_err(to_ui_error)?;
    refresh_watcher(&watcher);
    Ok(created)
}

#[tauri::command]
pub async fn watched_folder_update(
    state: State<'_, Option<Supervisor>>,
    watcher: State<'_, Watcher>,
    id: i64,
    changes: Value,
) -> Result<Value, Value> {
    let updated = supervisor(&state)?
        .request(
            reqwest::Method::PATCH,
            &format!("/v1/watched-folders/{id}"),
            Some(&changes),
            None,
        )
        .await
        .map_err(to_ui_error)?;
    refresh_watcher(&watcher);
    Ok(updated)
}

/// Stops watching. Never deletes or moves anything in the folder.
#[tauri::command]
pub async fn watched_folder_remove(
    state: State<'_, Option<Supervisor>>,
    watcher: State<'_, Watcher>,
    id: i64,
) -> Result<(), Value> {
    supervisor(&state)?
        .request(
            reqwest::Method::DELETE,
            &format!("/v1/watched-folders/{id}"),
            None,
            None,
        )
        .await
        .map_err(to_ui_error)?;
    refresh_watcher(&watcher);
    Ok(())
}

#[tauri::command]
pub async fn watched_folder_files(
    state: State<'_, Option<Supervisor>>,
    id: i64,
) -> Result<Value, Value> {
    supervisor(&state)?
        .request(
            reqwest::Method::GET,
            &format!("/v1/watched-folders/{id}/files"),
            None,
            None,
        )
        .await
        .map_err(to_ui_error)
}
