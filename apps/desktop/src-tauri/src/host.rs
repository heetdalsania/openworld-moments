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

#[derive(Clone)]
struct CurrentLibrary {
    path: PathBuf,
    configuration_error: bool,
}

/// Where the worker comes from. Release builds on Windows (M29) and macOS (M34) start
/// it from the bundle's `runtime/` folder; `OWM_WORKER_PYTHON` overrides; debug builds
/// fall back to the repository's virtualenv. Every path is absolute: no shell `PATH`.
fn worker_command<R: Runtime>(app: &AppHandle<R>) -> Option<WorkerCommand> {
    if crate::platform::bundled_worker(&crate::platform::facts()) {
        let runtime = app.path().resource_dir().ok()?.join("runtime");
        return Some(WorkerCommand {
            program: runtime.join(crate::platform::WORKER_EXECUTABLE),
            args: vec!["-m".into(), "openworld_moments.worker".into()],
            cwd: Some(runtime),
        });
    }
    let repo = development_repo();
    let python = std::env::var_os("OWM_WORKER_PYTHON")
        .map(PathBuf::from)
        .or_else(|| {
            let venv = crate::platform::venv_python(repo.as_ref()?);
            venv.exists().then_some(venv)
        })?;
    Some(WorkerCommand {
        program: python,
        args: vec!["-m".into(), "openworld_moments.worker".into()],
        cwd: repo
            .map(|r| r.join("services/media-worker"))
            .filter(|p| p.exists()),
    })
}

/// The source checkout, in debug builds only. Release binaries must not contain the
/// build machine's paths (M30 artifact scan), so the path is compiled out entirely
/// instead of being left to dead-code elimination.
fn development_repo() -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    {
        Some(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../.."))
    }
    #[cfg(not(debug_assertions))]
    {
        None
    }
}

pub fn setup<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    let Some(command) = worker_command(app) else {
        app.manage(None::<Supervisor>);
        app.manage(None::<WatchService<WorkerSink>> as Watcher);
        app.manage(None::<PhoneGateway> as Phone);
        return Ok(());
    };
    let dirs = crate::platform::app_dirs(app)?;
    let macos = crate::platform::facts().family == crate::platform::Family::Macos;
    let selection = if macos {
        crate::library_location::load(&dirs.data)
    } else {
        Ok(None)
    };
    let (library, existing, configuration_error) = match selection {
        Ok(Some(selected)) => (selected.path, true, false),
        Ok(None) => (dirs.library(), false, false),
        // Fail closed, but keep Settings usable so native selection can repair it.
        Err(_) => (dirs.data.join("unavailable-library-selection"), true, true),
    };
    app.manage(CurrentLibrary {
        path: library.clone(),
        configuration_error,
    });
    // No phone session runs yet: leftovers are from a crash.
    let phone_staging = if crate::platform::facts().family == crate::platform::Family::Macos {
        dirs.temp.join("phone")
    } else {
        library.join("staging").join("phone")
    };
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
    let mut config = SupervisorConfig::new(command, library);
    if existing {
        config.extra_args.push("--existing-library".into());
    }
    if crate::platform::facts().family == crate::platform::Family::Macos {
        config.extra_args.extend([
            "--cache-dir".into(),
            dirs.cache.to_string_lossy().into_owned(),
            "--log-dir".into(),
            dirs.logs.to_string_lossy().into_owned(),
        ]);
    }
    let supervisor = Supervisor::new(config);
    app.manage(Some(supervisor.clone()));

    let watcher = WatchService::new(WorkerSink(supervisor.clone()), WatchConfig::default());
    app.manage(Some(watcher.clone()) as Watcher);
    tauri::async_runtime::spawn(watcher.clone().run());

    let (lifecycle_tx, mut lifecycle_rx) = tokio::sync::mpsc::unbounded_channel();
    crate::platform::observe_lifecycle(lifecycle_tx);
    let lifecycle = crate::lifecycle::Lifecycle::new(supervisor.clone(), watcher.clone(), phone);
    app.manage(lifecycle.clone());
    let initial_lifecycle = lifecycle.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = lifecycle_rx.recv().await {
            lifecycle.handle(event).await;
        }
    });

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
        initial_lifecycle
            .handle(crate::platform::LifecycleEvent::Wake)
            .await;
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
        && let Some(lifecycle) = app.try_state::<crate::lifecycle::Lifecycle>()
    {
        tauri::async_runtime::block_on(lifecycle.shutdown());
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
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, Value> {
    if !crate::media::api_route_allowed(&method, &path) {
        return Err(crate::media::route_refused());
    }
    let body = if method == "POST" && path == "/v1/diagnostics" {
        Some(with_host_platform(&app, body))
    } else {
        body
    };
    let method = match method.as_str() {
        "GET" => reqwest::Method::GET,
        "POST" => reqwest::Method::POST,
        "PUT" => reqwest::Method::PUT,
        "DELETE" => reqwest::Method::DELETE,
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

/// Re-select the configured root through the native panel. A different folder is
/// refused: reauthorization must retain this folder's history and import identities.
#[tauri::command]
pub async fn watched_folder_reauthorize(
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    watcher: State<'_, Watcher>,
    id: i64,
) -> Result<bool, Value> {
    let folders = supervisor(&state)?
        .request(reqwest::Method::GET, "/v1/watched-folders", None, None)
        .await
        .map_err(to_ui_error)?;
    let root = folders
        .as_array()
        .and_then(|list| list.iter().find(|f| f["id"].as_i64() == Some(id)))
        .and_then(|f| f["path"].as_str())
        .map(PathBuf::from)
        .ok_or_else(crate::media::route_refused)?;
    use tauri_plugin_dialog::DialogExt;
    let selected = tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app.dialog().file().set_title("Select the same watched folder to restore access").blocking_pick_folder() else { return Ok(false); };
        let path = file.into_path().map_err(|_| crate::media::route_refused())?;
        if !same_folder(&root, &path) {
            return Err(json!({"code":"watch.different_folder", "message":"Select the same watched folder. Add a different location as a new watched folder.", "retryable":true}));
        }
        crate::watch::fsprobe::folder_available(&path).map_err(|_| json!({"code":"watch.access_required", "message":"The folder is still unavailable. Reconnect the drive, download the folder, or allow Files and Folders access in macOS Privacy & Security.", "retryable":true}))?;
        Ok::<_, Value>(true)
    }).await.map_err(|_| unavailable())??;
    if selected && let Some(watcher) = watcher.inner() {
        watcher.resume();
    }
    Ok(selected)
}

fn same_folder(configured: &std::path::Path, selected: &std::path::Path) -> bool {
    if configured == selected {
        return true;
    }
    match (
        std::fs::canonicalize(configured),
        std::fs::canonicalize(selected),
    ) {
        (Ok(left), Ok(right)) => left == right,
        _ => false,
    }
}

/// Extension the saved file must have for each M27 export format (fixed by the host).
pub fn export_extension(format: &str) -> Option<&'static str> {
    match format {
        "project" => Some("json"),
        "events" => Some("jsonl"),
        "srt" => Some("srt"),
        "vtt" => Some("vtt"),
        "csv" => Some("csv"),
        "otio" => Some("otio"),
        "fcpxml" => Some("fcpxml"),
        "manifest" => Some("json"),
        _ => None,
    }
}

/// The worker's suggested name when it is a plain name with the expected extension.
pub fn export_filename(suggested: Option<&str>, extension: &str) -> String {
    suggested
        .filter(|name| {
            name.len() <= 100
                && name.ends_with(&format!(".{extension}"))
                && !name.starts_with('.')
                && name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        })
        .map(str::to_owned)
        .unwrap_or_else(|| format!("export.{extension}"))
}

async fn save_worker_export(
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    method: reqwest::Method,
    path: String,
    body: Option<Value>,
    extension: &'static str,
) -> Result<Value, Value> {
    let method_name = method.as_str().to_owned();
    if !crate::media::api_route_allowed(&method_name, &path) {
        return Err(crate::media::route_refused());
    }
    let result = supervisor(&state)?
        .request(method, &path, body.as_ref(), None)
        .await
        .map_err(to_ui_error)?;
    let content = result
        .get("content")
        .and_then(Value::as_str)
        .filter(|c| c.len() <= 16 * 1024 * 1024 && !c.contains('\0'))
        .ok_or_else(unavailable)?
        .to_owned();
    let name = export_filename(result.get("filename").and_then(Value::as_str), extension);
    let warnings = result.get("warnings").cloned().unwrap_or_else(|| json!([]));
    use tauri_plugin_dialog::DialogExt;
    let saved = tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app.dialog().file().add_filter(extension, &[extension]).set_file_name(&name).blocking_save_file() else { return Ok(false) };
        let path = file.into_path().map_err(|_| crate::media::route_refused())?;
        crate::calibration::write_export(&path, content.as_bytes(), extension).map_err(|_| json!({"code":"export.save_failed","message":"Choose a new filename with the expected extension. Existing files are never replaced.","retryable":true}))?;
        Ok::<bool, Value>(true)
    })
    .await
    .map_err(|_| unavailable())??;
    Ok(json!({ "saved": saved, "warnings": warnings }))
}

/// M27: save an open-format export of the saved project. The host fetches the content
/// itself and fixes the extension; the webview never names a path or sends content.
#[tauri::command]
pub async fn project_export(
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    project_id: String,
    format: String,
    include_paths: bool,
) -> Result<Value, Value> {
    let extension = match export_extension(&format) {
        Some(ext) if format != "manifest" => ext,
        _ => return Err(crate::media::route_refused()),
    };
    let body = json!({ "format": format, "include_paths": include_paths });
    let path = format!("/v1/projects/{project_id}/exports");
    save_worker_export(
        app,
        state,
        reqwest::Method::POST,
        path,
        Some(body),
        extension,
    )
    .await
}

/// M31: save the redacted diagnostics report. The user previewed the same text; the
/// host fetches it again itself, so the webview never sends content or a path.
#[tauri::command]
pub async fn diagnostics_export(
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    include_messages: bool,
) -> Result<Value, Value> {
    let body = with_host_platform(&app, Some(json!({ "include_messages": include_messages })));
    save_worker_export(
        app,
        state,
        reqwest::Method::POST,
        "/v1/diagnostics".to_owned(),
        Some(body),
        "json",
    )
    .await
}

/// M33: diagnostics carry the host's platform report. The host writes it, replacing
/// anything the webview sent, so the preview and the saved file show the same facts.
fn with_host_platform<R: Runtime>(app: &AppHandle<R>, body: Option<Value>) -> Value {
    let version = app.package_info().version.to_string();
    host_platform_body(
        body,
        crate::platform::capabilities(&version, &crate::platform::facts()),
    )
}

fn host_platform_body(body: Option<Value>, host: Value) -> Value {
    let mut body = match body {
        Some(Value::Object(map)) => map,
        _ => serde_json::Map::new(),
    };
    body.insert("host".to_owned(), host);
    Value::Object(body)
}

fn library_dir<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, Value> {
    if let Some(library) = app.try_state::<CurrentLibrary>() {
        return if library.configuration_error {
            Err(unavailable())
        } else {
            Ok(library.path.clone())
        };
    }
    crate::platform::app_dirs(app)
        .map(|dirs| dirs.library())
        .map_err(|_| unavailable())
}

/// The active path is deliberate user-visible Settings data, never diagnostics.
#[tauri::command]
pub fn library_location(app: AppHandle) -> Result<Value, Value> {
    if crate::platform::facts().family != crate::platform::Family::Macos {
        return Ok(json!({"supported":false}));
    }
    let path = library_dir(&app).ok();
    Ok(
        json!({"supported":true, "path":path, "available":path.as_ref().is_some_and(|p| p.join("database.sqlite3").is_file())}),
    )
}

/// Locate a library moved while the app was closed. Switching is deferred to a new
/// launch; an active library is never copied, moved, or detached from its jobs.
#[tauri::command]
pub async fn library_select(app: AppHandle) -> Result<Value, Value> {
    if crate::platform::facts().family != crate::platform::Family::Macos {
        return Err(crate::media::route_refused());
    }
    let data = crate::platform::app_dirs(&app)
        .map_err(|_| unavailable())?
        .data;
    let current = library_dir(&app).ok();
    use tauri_plugin_dialog::DialogExt;
    let picker = app.clone();
    let selection = tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = picker.dialog().file().set_title("Choose an existing OpenWorld Moments library").blocking_pick_folder() else { return Ok(None); };
        let path = file.into_path().map_err(|_| crate::media::route_refused())?;
        crate::library_location::save(&data, &path).map_err(|_| json!({"code":"library.selection_unavailable", "message":"Select a downloaded, readable library folder containing database.sqlite3. The current library was kept.", "retryable":true}))?;
        Ok::<_, Value>(Some(path))
    }).await.map_err(|_| unavailable())??;
    let Some(path) = selection else {
        return Ok(json!({"selected":false}));
    };
    let restart = !current
        .as_deref()
        .is_some_and(|current| same_folder(current, &path));
    if !restart && let Some(lifecycle) = app.try_state::<crate::lifecycle::Lifecycle>() {
        lifecycle
            .handle(crate::platform::LifecycleEvent::Wake)
            .await;
    }
    Ok(json!({"selected":true,"restart_required":restart}))
}

fn reveal_failed() -> Value {
    json!({"code":"reveal.failed","message":"The file manager could not be opened. The file is still in your library.","retryable":true})
}

/// M31: show a finished render in the file manager. The host reads the render record
/// and checks the output is a regular file inside the library before showing it.
#[tauri::command]
pub async fn render_reveal(
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    render_id: String,
) -> Result<Value, Value> {
    if !crate::media::is_id(&render_id, "job_") {
        return Err(crate::media::route_refused());
    }
    let record = supervisor(&state)?
        .request(
            reqwest::Method::GET,
            &format!("/v1/renders/{render_id}"),
            None,
            None,
        )
        .await
        .map_err(to_ui_error)?;
    let missing = || json!({"code":"render.output_missing","message":"The rendered file is no longer in the library. Render again to recreate it.","retryable":false});
    let relative = record
        .pointer("/output/relative_path")
        .and_then(Value::as_str)
        .ok_or_else(missing)?
        .to_owned();
    let library = library_dir(&app)?;
    let path = crate::reveal::render_output(&library, &relative).ok_or_else(missing)?;
    crate::reveal::show(&path, true).map_err(|_| reveal_failed())?;
    Ok(json!({ "shown": true }))
}

/// M31: open the library folder (where imports, renders and the database live).
#[tauri::command]
pub fn library_reveal(app: AppHandle) -> Result<Value, Value> {
    let library = library_dir(&app)?;
    if !library.is_dir() {
        return Err(
            json!({"code":"library.unavailable","message":"The library folder has not been created yet. Start the app once the media worker is running.","retryable":true}),
        );
    }
    crate::reveal::show(&library, false).map_err(|_| reveal_failed())?;
    Ok(json!({ "shown": true }))
}

/// M27: save a completed render's stored manifest.
#[tauri::command]
pub async fn render_manifest_export(
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    render_id: String,
) -> Result<Value, Value> {
    let path = format!("/v1/renders/{render_id}/manifest");
    save_worker_export(app, state, reqwest::Method::GET, path, None, "json").await
}

/// Export only the worker-validated, saved media-free patch. No webview path input.
#[tauri::command]
pub async fn calibration_export_patch(
    app: AppHandle,
    state: State<'_, Option<Supervisor>>,
    profile_id: String,
) -> Result<bool, Value> {
    let path = format!("/v1/profiles/{profile_id}/calibration");
    if !crate::media::api_route_allowed("GET", &path) {
        return Err(crate::media::route_refused());
    }
    let doc = supervisor(&state)?
        .request(reqwest::Method::GET, &path, None, None)
        .await
        .map_err(to_ui_error)?;
    let patch = doc.get("patch").filter(|p| p.is_object())
        .ok_or_else(|| json!({"code":"calibration.unsaved", "message":"Save local overrides before exporting.", "retryable":false}))?;
    let bytes = serde_json::to_vec_pretty(patch).map_err(|_| unavailable())?;
    calibration_save(app, bytes, "profile-patch.json", "json").await
}

/// Crop export is a separate explicit action and never enters a profile patch.
#[tauri::command]
pub async fn calibration_export_sample(app: AppHandle, data: Vec<u8>) -> Result<bool, Value> {
    if data.len() > 4 * 1024 * 1024 || !data.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Err(crate::media::route_refused());
    }
    calibration_save(app, data, "roi-sample.png", "png").await
}

async fn calibration_save(
    app: AppHandle,
    bytes: Vec<u8>,
    name: &'static str,
    ext: &'static str,
) -> Result<bool, Value> {
    use tauri_plugin_dialog::DialogExt;
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app.dialog().file().add_filter(ext, &[ext]).set_file_name(name).blocking_save_file() else { return Ok(false) };
        let path = file.into_path().map_err(|_| crate::media::route_refused())?;
        crate::calibration::write_export(&path, &bytes, ext).map_err(|_| json!({"code":"calibration.export_failed", "message":"Choose a new filename with the expected extension. Existing files are never replaced.", "retryable":true}))?;
        Ok(true)
    }).await.map_err(|_| unavailable())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn diagnostics_body_gets_the_host_report_and_keeps_the_choice() {
        let host = json!({"schema_version": "1.25"});
        let body = host_platform_body(
            Some(json!({"include_messages": true, "host": "fake"})),
            host.clone(),
        );
        assert_eq!(body, json!({"include_messages": true, "host": host}));
        assert_eq!(
            host_platform_body(None, host.clone()),
            json!({"host": host})
        );
        assert_eq!(
            host_platform_body(Some(json!([1])), host.clone()),
            json!({"host": host})
        );
    }

    #[test]
    fn export_extensions_are_fixed_per_format() {
        assert_eq!(export_extension("otio"), Some("otio"));
        assert_eq!(export_extension("project"), Some("json"));
        assert_eq!(export_extension("events"), Some("jsonl"));
        assert_eq!(export_extension("exe"), None);
        assert_eq!(export_extension("../otio"), None);
    }

    #[test]
    fn suggested_export_names_must_be_plain_names() {
        assert_eq!(export_filename(Some("Escape.otio"), "otio"), "Escape.otio");
        for bad in [
            "../Escape.otio",
            "Escape.otio.exe",
            "Escape.json",
            ".hidden.otio",
            "a/b.otio",
            "C:\\x.otio",
            "Café.otio",
        ] {
            assert_eq!(export_filename(Some(bad), "otio"), "export.otio", "{bad}");
        }
        assert_eq!(export_filename(None, "srt"), "export.srt");
    }
}

#[cfg(test)]
mod location_tests {
    use super::same_folder;
    #[test]
    fn reauthorization_refuses_another_root_and_accepts_a_canonical_alias() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("Captures ✓");
        let other = dir.path().join("Other");
        std::fs::create_dir(&root).unwrap();
        std::fs::create_dir(&other).unwrap();
        assert!(same_folder(&root, &root));
        assert!(same_folder(&root, &std::fs::canonicalize(&root).unwrap()));
        assert!(!same_folder(&root, &other));
        assert!(!same_folder(&root, &dir.path().join("missing")));
    }
}
