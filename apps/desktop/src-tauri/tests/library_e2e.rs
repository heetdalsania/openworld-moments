// SPDX-License-Identifier: AGPL-3.0-or-later
//! End-to-end import-to-playback path (M09), against the real worker and FFmpeg:
//! import a synthetic clip, prepare its derived media, and fetch the proxy, original,
//! thumbnail, and waveform exactly as the player does, through `owm-media`. Also
//! checks the UI route allowlist and a worker restart while jobs exist.
//!
//! Requires the repository's Python environment (`uv sync --all-packages`) and
//! FFmpeg. Without FFmpeg the test is skipped, unless `OWM_REQUIRE_FFMPEG=1` (CI).
//!
//! Run: `cargo test -p openworld-moments-desktop --test library_e2e`

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use openworld_moments_desktop_lib::media::{api_route_allowed, serve};
use openworld_moments_desktop_lib::worker::{
    Supervisor, SupervisorConfig, WorkerCommand, WorkerStatus,
};
use serde_json::{Value, json};
use tokio::time::{sleep, timeout};

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
    assert!(python.exists(), "worker Python not found at {python:?}");
    WorkerCommand {
        program: python,
        args: vec!["-m".into(), "openworld_moments.worker".into()],
        cwd: Some(root.join("services/media-worker")),
    }
}

fn ffmpeg() -> Option<PathBuf> {
    let program = std::env::var_os("OWM_FFMPEG")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("ffmpeg"));
    let works = Command::new(&program)
        .arg("-version")
        .output()
        .is_ok_and(|o| o.status.success());
    if works {
        return Some(program);
    }
    assert!(
        std::env::var("OWM_REQUIRE_FFMPEG").as_deref() != Ok("1"),
        "FFmpeg is required (OWM_REQUIRE_FFMPEG=1)"
    );
    None
}

/// A 2-second synthetic HEVC-free clip in MKV, so the policy asks for a proxy.
fn make_clip(ffmpeg: &Path, target: &Path) {
    let status = Command::new(ffmpeg)
        .args(["-hide_banner", "-loglevel", "error", "-nostdin", "-y"])
        .args([
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=2",
        ])
        .args([
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
        ])
        .args([
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
        ])
        .args(["-c:a", "aac", "-shortest"])
        .arg(target)
        .status()
        .expect("ffmpeg runs");
    assert!(status.success(), "fixture clip");
}

async fn ui(supervisor: &Supervisor, method: &str, path: &str, body: Option<Value>) -> Value {
    assert!(api_route_allowed(method, path), "UI route {method} {path}");
    let method = if method == "GET" {
        reqwest::Method::GET
    } else {
        reqwest::Method::POST
    };
    supervisor
        .request(method, path, body.as_ref(), None)
        .await
        .unwrap_or_else(|e| panic!("{path}: {e:?}"))
}

async fn finished(supervisor: &Supervisor, job_id: &str) -> Value {
    timeout(Duration::from_secs(120), async {
        loop {
            let job = ui(supervisor, "GET", &format!("/v1/jobs/{job_id}"), None).await;
            if matches!(
                job["state"].as_str(),
                Some("ready" | "failed" | "cancelled")
            ) {
                return job;
            }
            sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .expect("job finishes")
}

/// Wait until the worker is ready again after at least `restarts` restarts.
async fn wait_ready(supervisor: &Supervisor, restarts: u32) {
    let mut rx = supervisor.subscribe_status();
    timeout(Duration::from_secs(60), async {
        loop {
            if matches!(*rx.borrow_and_update(), WorkerStatus::Ready { restarts: r, .. } if r >= restarts)
            {
                return;
            }
            rx.changed().await.unwrap();
        }
    })
    .await
    .expect("worker ready");
}

#[tokio::test(flavor = "multi_thread")]
async fn import_prepare_and_play() {
    let Some(ffmpeg) = ffmpeg() else {
        eprintln!("skipping: FFmpeg not found");
        return;
    };
    let dir = tempfile::tempdir().unwrap();
    let captures = dir.path().join("My Captures");
    std::fs::create_dir(&captures).unwrap();
    let clip = captures.join("clip one.mkv");
    make_clip(&ffmpeg, &clip);
    let original = std::fs::read(&clip).unwrap();

    let mut config = SupervisorConfig::new(worker_command(), dir.path().join("library"));
    config.restart_window = Duration::from_secs(60);
    let supervisor = Supervisor::new(config);
    supervisor.start().await.expect("worker starts");

    // Import, as the Import button does.
    let job = ui(
        &supervisor,
        "POST",
        "/v1/imports",
        Some(json!({ "paths": [clip], "mode": "reference", "recursive": false })),
    )
    .await;
    let job = finished(&supervisor, job["id"].as_str().unwrap()).await;
    assert_eq!(job["state"], "ready", "{job}");
    let asset = job["result"]["items"][0]["asset_id"]
        .as_str()
        .unwrap()
        .to_string();

    // The library lists it, newest first.
    let assets = ui(&supervisor, "GET", "/v1/assets?order=newest&limit=60", None).await;
    assert_eq!(assets[0]["id"], asset.as_str());

    // Prepare playback, as the asset view does.
    let job = ui(
        &supervisor,
        "POST",
        &format!("/v1/assets/{asset}/derived"),
        Some(json!({ "idempotency_key": format!("derive-auto:{asset}") })),
    )
    .await;
    let job = finished(&supervisor, job["id"].as_str().unwrap()).await;
    assert_eq!(job["state"], "ready", "{job}");
    let derived = ui(
        &supervisor,
        "GET",
        &format!("/v1/assets/{asset}/derived"),
        None,
    )
    .await;
    assert_eq!(derived["proxy_decision"]["needed"], true); // MKV → proxy
    for artifact in derived["artifacts"].as_array().unwrap() {
        assert_eq!(artifact["status"], "ready", "{artifact}");
    }

    // Play: the player's first request is a small range, then the rest.
    let first = serve(
        &supervisor,
        &format!("/asset/{asset}/proxy"),
        Some("bytes=0-1"),
    )
    .await;
    assert_eq!(first.status, 206);
    assert_eq!(first.body.len(), 2);
    let total: usize = first
        .headers
        .iter()
        .find(|(k, _)| *k == "Content-Range")
        .and_then(|(_, v)| v.rsplit('/').next())
        .and_then(|n| n.parse().ok())
        .unwrap();
    let rest = serve(
        &supervisor,
        &format!("/asset/{asset}/proxy"),
        Some("bytes=0-"),
    )
    .await;
    assert_eq!(rest.status, 206);
    assert_eq!(rest.body.len(), total);
    assert_eq!(&rest.body[4..8], b"ftyp");
    assert!(
        rest.headers
            .contains(&("Content-Type", "video/mp4".to_string()))
    );

    let source = serve(&supervisor, &format!("/asset/{asset}/original"), None).await;
    assert_eq!(source.status, 200);
    assert_eq!(source.body, original);
    let thumb = serve(&supervisor, &format!("/asset/{asset}/thumbnail/1"), None).await;
    assert_eq!(thumb.status, 200);
    assert_eq!(&thumb.body[..3], &[0xff, 0xd8, 0xff]);
    let wave = serve(&supervisor, &format!("/asset/{asset}/waveform"), None).await;
    assert_eq!((wave.status, &wave.body[..4]), (200, &b"OWMW"[..]));

    // Errors are explained, never paths.
    let missing = serve(&supervisor, &format!("/asset/{asset}/thumbnail/99"), None).await;
    assert_eq!(missing.status, 404);
    let bad = serve(&supervisor, "/asset/../../etc/passwd/original", None).await;
    assert_eq!(bad.status, 400);
    for response in [&missing, &bad] {
        let text = String::from_utf8_lossy(&response.body);
        assert!(!text.contains("My Captures"), "{text}");
    }

    // A missing original is reported as such, while the proxy still plays.
    std::fs::rename(&clip, captures.join("moved.mkv")).unwrap();
    let gone = serve(&supervisor, &format!("/asset/{asset}/original"), None).await;
    assert_eq!(gone.status, 404);
    assert!(String::from_utf8_lossy(&gone.body).contains("media.source_missing"));
    let still = serve(
        &supervisor,
        &format!("/asset/{asset}/proxy"),
        Some("bytes=0-1"),
    )
    .await;
    assert_eq!(still.status, 206);

    // Worker restart while the UI is open: durable jobs and assets are still there.
    supervisor.simulate_crash().await;
    wait_ready(&supervisor, 1).await;
    let jobs = ui(&supervisor, "GET", "/v1/jobs?limit=200", None).await;
    let kinds: Vec<&str> = jobs
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|j| j["kind"].as_str())
        .collect();
    assert!(
        kinds.contains(&"import") && kinds.contains(&"proxy"),
        "{kinds:?}"
    );
    let after = serve(
        &supervisor,
        &format!("/asset/{asset}/proxy"),
        Some("bytes=0-1"),
    )
    .await;
    assert_eq!(after.status, 206);

    supervisor.stop().await;
    assert_eq!(
        std::fs::read(captures.join("moved.mkv")).unwrap(),
        original,
        "the original is never modified"
    );
}
