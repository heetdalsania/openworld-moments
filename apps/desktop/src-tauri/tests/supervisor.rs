// SPDX-License-Identifier: AGPL-3.0-or-later
//! Supervisor integration tests against the real Python worker.
//!
//! Requires the repository's Python environment (`uv sync --all-packages`).
//! Override the interpreter with OWM_WORKER_PYTHON.

use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::time::Duration;

use openworld_moments_desktop_lib::worker::{
    SeqCheck, Supervisor, SupervisorConfig, SupervisorError, WorkerCommand, WorkerStatus,
};
use serde_json::json;
use tokio::time::{sleep, timeout};

const COR: &str = "cor_01JCBQ00000000000000000008";

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

fn worker_command() -> WorkerCommand {
    let root = repo_root();
    let python = std::env::var_os("OWM_WORKER_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            if cfg!(windows) {
                root.join(".venv/Scripts/python.exe")
            } else {
                root.join(".venv/bin/python")
            }
        });
    assert!(
        python.exists(),
        "worker Python not found at {python:?}; run `uv sync --all-packages`"
    );
    WorkerCommand {
        program: python,
        args: vec!["-m".into(), "openworld_moments.worker".into()],
        cwd: Some(root.join("services/media-worker")),
    }
}

fn config(dir: &tempfile::TempDir) -> SupervisorConfig {
    let mut config = SupervisorConfig::new(worker_command(), dir.path().join("library"));
    config.restart_window = Duration::from_secs(60);
    config
}

async fn wait_status(
    supervisor: &Supervisor,
    want: impl Fn(&WorkerStatus) -> bool,
) -> WorkerStatus {
    let mut rx = supervisor.subscribe_status();
    timeout(Duration::from_secs(60), async {
        loop {
            let current = rx.borrow_and_update().clone();
            if want(&current) {
                return current;
            }
            rx.changed().await.unwrap();
        }
    })
    .await
    .expect("status did not arrive in time")
}

async fn wait_job_state(supervisor: &Supervisor, id: &str, state: &str) -> serde_json::Value {
    timeout(Duration::from_secs(60), async {
        loop {
            if let Ok(job) = supervisor.get_job(id).await
                && job["state"] == state
            {
                return job;
            }
            sleep(Duration::from_millis(50)).await;
        }
    })
    .await
    .unwrap_or_else(|_| panic!("job {id} never reached {state}"))
}

#[tokio::test]
async fn starts_authenticates_and_stops() {
    let dir = tempfile::tempdir().unwrap();
    let supervisor = Supervisor::new(config(&dir));
    let info = supervisor.start().await.expect("worker starts");
    assert!(info.port > 0);
    assert!(matches!(supervisor.status(), WorkerStatus::Ready { .. }));
    assert_eq!(supervisor.health().await.unwrap()["status"], "ok");

    // Requests without the token are rejected by the worker.
    let anonymous = reqwest::Client::builder().no_proxy().build().unwrap();
    let response = anonymous
        .get(format!("http://127.0.0.1:{}/v1/health", info.port))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 401);
    let body: serde_json::Value = response.json().await.unwrap();
    assert_eq!(body["code"], "auth.missing_token");

    supervisor.stop().await;
    assert_eq!(supervisor.status(), WorkerStatus::Stopped);
    assert!(matches!(
        supervisor.health().await,
        Err(SupervisorError::NotRunning)
    ));
    // Nothing listens on the port once the worker exits. (A re-bind is not a
    // reliable check: closed connections may leave the port in TIME_WAIT.)
    assert!(TcpStream::connect(("127.0.0.1", info.port)).is_err());
}

#[tokio::test]
async fn progress_events_are_ordered_and_carry_correlation_ids() {
    let dir = tempfile::tempdir().unwrap();
    let supervisor = Supervisor::new(config(&dir));
    supervisor.start().await.unwrap();
    let mut events = supervisor.connect_events().await.unwrap();
    let job = supervisor
        .submit_job("diagnostic", json!({"steps": 6, "step_ms": 5}), Some(COR))
        .await
        .unwrap();
    let id = job["id"].as_str().unwrap().to_string();

    let mut seen = Vec::new();
    loop {
        let (event, check) = timeout(Duration::from_secs(30), events.next())
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(check, SeqCheck::InOrder);
        assert_eq!(event.job_id, id);
        assert_eq!(event.correlation_id.as_deref(), Some(COR));
        let done = event.state == "ready";
        seen.push(event);
        if done {
            break;
        }
    }
    let seqs: Vec<u64> = seen.iter().map(|e| e.seq).collect();
    assert!(seqs.windows(2).all(|w| w[1] == w[0] + 1), "{seqs:?}");
    let states: Vec<&str> = seen
        .iter()
        .filter(|e| e.kind == "state")
        .map(|e| e.state.as_str())
        .collect();
    assert_eq!(states, ["queued", "analyzing", "ready"]);
    assert_eq!(events.malformed, 0);
    supervisor.stop().await;
}

#[tokio::test]
async fn cancelling_the_synthetic_job_reaches_cancelled() {
    let dir = tempfile::tempdir().unwrap();
    let supervisor = Supervisor::new(config(&dir));
    supervisor.start().await.unwrap();
    let job = supervisor
        .submit_job("diagnostic", json!({"steps": 1000, "step_ms": 20}), None)
        .await
        .unwrap();
    let id = job["id"].as_str().unwrap();
    wait_job_state(&supervisor, id, "analyzing").await;
    supervisor.cancel_job(id).await.unwrap();
    let cancelled = wait_job_state(&supervisor, id, "cancelled").await;
    let done = cancelled["progress"]["done"].as_u64().unwrap_or(0);
    sleep(Duration::from_millis(200)).await;
    assert_eq!(
        supervisor.get_job(id).await.unwrap()["progress"]["done"]
            .as_u64()
            .unwrap_or(0),
        done,
        "work continued after cancel"
    );
    supervisor.stop().await;
}

#[tokio::test]
async fn crash_is_detected_restart_keeps_job_records() {
    let dir = tempfile::tempdir().unwrap();
    let supervisor = Supervisor::new(config(&dir));
    let first = supervisor.start().await.unwrap();
    let job = supervisor
        .submit_job("diagnostic", json!({"steps": 300, "step_ms": 10}), None)
        .await
        .unwrap();
    let id = job["id"].as_str().unwrap().to_string();
    wait_job_state(&supervisor, &id, "analyzing").await;

    supervisor.simulate_crash().await;
    wait_status(&supervisor, |s| {
        matches!(s, WorkerStatus::Restarting { .. })
    })
    .await;
    let ready = wait_status(&supervisor, |s| {
        matches!(s, WorkerStatus::Ready { restarts: 1, .. })
    })
    .await;
    let WorkerStatus::Ready { pid, .. } = ready else {
        unreachable!()
    };
    assert_ne!(pid, first.pid, "a new worker process is running");

    // The durable record survived and the idempotent job was requeued and finished.
    let finished = wait_job_state(&supervisor, &id, "ready").await;
    assert_eq!(finished["attempt"], 2);
    supervisor.stop().await;
}

#[tokio::test]
async fn repeated_crashes_end_in_failed_with_stderr_tail() {
    let dir = tempfile::tempdir().unwrap();
    let mut config = config(&dir);
    config.max_restarts = 1;
    let supervisor = Supervisor::new(config);
    supervisor.start().await.unwrap();
    supervisor.simulate_crash().await;
    wait_status(&supervisor, |s| {
        matches!(s, WorkerStatus::Ready { restarts: 1, .. })
    })
    .await;
    supervisor.simulate_crash().await;
    let failed = wait_status(&supervisor, |s| matches!(s, WorkerStatus::Failed { .. })).await;
    let WorkerStatus::Failed {
        code, stderr_tail, ..
    } = failed
    else {
        unreachable!()
    };
    assert_eq!(code, "worker.crash_loop");
    assert!(
        stderr_tail.contains("worker ready"),
        "stderr tail should hold recent worker logs"
    );
}

#[tokio::test]
async fn port_conflict_is_a_structured_startup_error() {
    let dir = tempfile::tempdir().unwrap();
    let busy = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let mut config = config(&dir);
    config.extra_args = vec![
        "--port".into(),
        busy.local_addr().unwrap().port().to_string(),
    ];
    let supervisor = Supervisor::new(config);
    let err = supervisor.start().await.unwrap_err();
    assert!(
        matches!(&err, SupervisorError::Startup { code, .. } if code == "worker.port_in_use"),
        "{err:?}"
    );
    assert!(
        matches!(supervisor.status(), WorkerStatus::Failed { ref code, .. } if code == "worker.port_in_use")
    );
}

#[tokio::test]
async fn missing_program_is_a_spawn_error() {
    let dir = tempfile::tempdir().unwrap();
    let mut config = config(&dir);
    config.command.program = dir.path().join("no-such-python");
    let err = Supervisor::new(config).start().await.unwrap_err();
    assert!(matches!(err, SupervisorError::Spawn(_)), "{err:?}");
}

#[tokio::test]
async fn early_exit_reports_stderr_without_the_token() {
    let dir = tempfile::tempdir().unwrap();
    let mut config = config(&dir);
    // An unknown flag makes the worker exit during argument parsing.
    config.extra_args = vec!["--no-such-flag".into()];
    let err = Supervisor::new(config).start().await.unwrap_err();
    let SupervisorError::Startup {
        code, stderr_tail, ..
    } = err
    else {
        panic!("{err:?}")
    };
    assert_eq!(code, "worker.exited");
    assert!(
        stderr_tail.contains("unrecognized arguments"),
        "{stderr_tail}"
    );
}

/// The real worker sink: folder config round trip and file decisions (M07). The
/// file is not valid media, so its import job fails, but exactly one is started.
#[tokio::test(flavor = "multi_thread")]
async fn worker_sink_round_trip() {
    use openworld_moments_desktop_lib::watch::fsprobe::{self, FileState};
    use openworld_moments_desktop_lib::watch::{Sink, WorkerSink};

    let dir = tempfile::tempdir().unwrap();
    let watched = dir.path().join("Xbox Game DVR");
    std::fs::create_dir(&watched).unwrap();
    std::fs::write(watched.join("clip.mp4"), b"not really a video").unwrap();
    let supervisor = Supervisor::new(config(&dir));
    supervisor.start().await.expect("worker starts");
    let created = supervisor
        .request(
            reqwest::Method::POST,
            "/v1/watched-folders",
            Some(&json!({ "path": watched, "source_kind": "xbox" })),
            None,
        )
        .await
        .expect("folder is created");
    let id = created["id"].as_i64().unwrap();

    let sink = WorkerSink(supervisor.clone());
    let folders = sink.folders().await.expect("folders load");
    assert_eq!(folders.len(), 1);
    assert_eq!(folders[0].id, id);
    assert!(folders[0].recursive && folders[0].enabled);

    // Report the file's real metadata, as the watcher would.
    let FileState::Local(meta) = fsprobe::file_state(&watched.join("clip.mp4")) else {
        panic!("the test file is a local file");
    };
    assert_eq!(
        sink.report_file(id, "clip.mp4", meta).await.unwrap(),
        "queued"
    );
    // The same version again never starts a second job. Depending on timing the
    // first import is still running, has failed for good (not a video), or has
    // failed retryably and waits in backoff.
    let again = sink.report_file(id, "clip.mp4", meta).await.unwrap();
    assert!(
        matches!(again.as_str(), "in_progress" | "known" | "backoff"),
        "{again}"
    );
    assert_eq!(
        sink.report_file(id, "notes.txt", meta).await.unwrap(),
        "ignored"
    );
    assert!(sink.report_file(id, "../escape.mp4", meta).await.is_err());
    sink.report_scan(id, true, true, None).await.unwrap();

    let jobs = supervisor.list_jobs().await.unwrap();
    let imports = jobs
        .as_array()
        .unwrap()
        .iter()
        .filter(|j| j["kind"] == "import")
        .count();
    assert_eq!(imports, 1);
    supervisor.stop().await;
    assert!(
        watched.join("clip.mp4").exists(),
        "the watched file is never touched"
    );
}

#[tokio::test]
async fn sleep_closes_phone_and_recovers_running_job_then_quit_refuses_a_late_wake() {
    use openworld_moments_desktop_lib::lifecycle::Lifecycle;
    use openworld_moments_desktop_lib::phone::{PhoneConfig, PhoneGateway};
    use openworld_moments_desktop_lib::platform::LifecycleEvent;
    use openworld_moments_desktop_lib::watch::{WatchConfig, WatchService, WorkerSink};
    let dir = tempfile::tempdir().unwrap();
    let supervisor = Supervisor::new(config(&dir));
    supervisor.start().await.unwrap();
    let watcher = WatchService::new(WorkerSink(supervisor.clone()), WatchConfig::default());
    let phone = PhoneGateway::new(PhoneConfig {
        command: worker_command(),
        staging_root: dir.path().join("phone"),
        session_seconds: 600,
        allow_loopback: true,
    });
    assert_eq!(phone.status().state, "idle");
    let active = phone
        .start(Some(supervisor.clone()), "127.0.0.1", 0)
        .await
        .unwrap();
    let port = active.port.unwrap();
    let job = supervisor
        .submit_job("diagnostic", json!({"steps":10000,"step_ms":10}), Some(COR))
        .await
        .unwrap();
    let id = job["id"].as_str().unwrap();
    wait_job_state(&supervisor, id, "analyzing").await;
    let lifecycle = Lifecycle::new(supervisor.clone(), watcher, phone.clone());
    lifecycle.handle(LifecycleEvent::Sleep).await;
    assert_eq!(supervisor.status(), WorkerStatus::Stopped);
    assert!(TcpStream::connect(("127.0.0.1", port)).is_err());
    assert!(phone.status().url.is_none());
    lifecycle.handle(LifecycleEvent::Wake).await;
    assert!(matches!(supervisor.status(), WorkerStatus::Ready { .. }));
    assert_ne!(phone.status().state, "active");
    let recovered = supervisor.get_job(id).await.unwrap();
    assert_ne!(recovered["state"], "ready");
    supervisor.cancel_job(id).await.unwrap();
    lifecycle.shutdown().await;
    lifecycle.handle(LifecycleEvent::Wake).await;
    assert_eq!(supervisor.status(), WorkerStatus::Stopped);
}
