// SPDX-License-Identifier: AGPL-3.0-or-later
//! Tauri integration for the worker supervisor: startup, UI events, commands, shutdown.

use std::path::PathBuf;
use std::time::Duration;

use serde_json::{Value, json};
use tauri::{AppHandle, Emitter, Manager, RunEvent, Runtime, State};

use crate::worker::{SeqCheck, Supervisor, SupervisorConfig, WorkerCommand, WorkerStatus};

/// UI event names.
pub const STATUS_EVENT: &str = "worker://status";
pub const JOB_EVENT: &str = "worker://job-event";
pub const RESYNC_EVENT: &str = "worker://resync";

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
        return Ok(());
    };
    let library = app.path().app_data_dir()?.join("library");
    let supervisor = Supervisor::new(SupervisorConfig::new(command, library));
    app.manage(Some(supervisor.clone()));

    let handle = app.clone();
    let mut status = supervisor.subscribe_status();
    tauri::async_runtime::spawn(async move {
        loop {
            let current = status.borrow_and_update().clone();
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

#[tauri::command]
pub async fn worker_list_jobs(state: State<'_, Option<Supervisor>>) -> Result<Value, Value> {
    supervisor(&state)?.list_jobs().await.map_err(to_ui_error)
}
