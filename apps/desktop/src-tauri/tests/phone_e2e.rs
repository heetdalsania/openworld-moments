// SPDX-License-Identifier: AGPL-3.0-or-later
//! "Import from phone" end to end (M10): the host starts the real upload gateway,
//! a "phone" uploads over HTTP, received files become managed `phone_upload` assets
//! through the real worker, and the gateway is unreachable before and after the
//! session. Binds 127.0.0.1 (tests only); the app offers private LAN addresses only.
//!
//! Requires the repository's Python environment and FFmpeg (skipped without FFmpeg
//! unless `OWM_REQUIRE_FFMPEG=1`).
//!
//! Run: `cargo test -p openworld-moments-desktop --test phone_e2e`

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use openworld_moments_desktop_lib::phone::{PhoneConfig, PhoneGateway, PhoneStatus};
use openworld_moments_desktop_lib::worker::{Supervisor, SupervisorConfig, WorkerCommand};
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
    if Command::new(&program)
        .arg("-version")
        .output()
        .is_ok_and(|o| o.status.success())
    {
        return Some(program);
    }
    assert!(
        std::env::var("OWM_REQUIRE_FFMPEG").as_deref() != Ok("1"),
        "FFmpeg is required (OWM_REQUIRE_FFMPEG=1)"
    );
    None
}

fn make_clip(ffmpeg: &Path, target: &Path) {
    let status = Command::new(ffmpeg)
        .args(["-hide_banner", "-loglevel", "error", "-nostdin", "-y"])
        .args([
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=1",
        ])
        .args([
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
        ])
        .args([
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
        ])
        .args(["-c:a", "aac", "-shortest", "-movflags", "+faststart"])
        .arg(target)
        .status()
        .expect("ffmpeg runs");
    assert!(status.success());
}

async fn wait_for(gateway: &PhoneGateway, want: impl Fn(&PhoneStatus) -> bool) -> PhoneStatus {
    timeout(Duration::from_secs(60), async {
        loop {
            let status = gateway.status();
            if want(&status) {
                return status;
            }
            sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .unwrap_or_else(|_| panic!("timed out; last status {:?}", gateway.status()))
}

async fn put(url: &str, name: &str, body: Vec<u8>) -> (u16, String) {
    let client = reqwest::Client::new();
    let response = client
        .put(format!("{url}files?name={name}"))
        .body(body)
        .send()
        .await
        .expect("upload request");
    let status = response.status().as_u16();
    (status, response.text().await.unwrap_or_default())
}

#[tokio::test(flavor = "multi_thread")]
async fn phone_uploads_become_library_assets() {
    let Some(ffmpeg) = ffmpeg() else {
        eprintln!("skipping: FFmpeg not found");
        return;
    };
    let dir = tempfile::tempdir().unwrap();
    let clip_path = dir.path().join("phone clip.mp4");
    make_clip(&ffmpeg, &clip_path);
    let clip = std::fs::read(&clip_path).unwrap();
    let library = dir.path().join("library");

    let supervisor = Supervisor::new(SupervisorConfig::new(worker_command(), library.clone()));
    supervisor.start().await.expect("worker starts");
    let staging_root = library.join("staging").join("phone");
    let gateway = PhoneGateway::new(PhoneConfig {
        command: worker_command(),
        staging_root: staging_root.clone(),
        session_seconds: 600,
        allow_loopback: true,
    });

    // Public and wildcard addresses are refused before anything listens.
    for bad in ["0.0.0.0", "8.8.8.8", "::1", "not-an-ip"] {
        let error = gateway
            .start(Some(supervisor.clone()), bad, 0)
            .await
            .unwrap_err();
        assert_eq!(error["code"], "phone.address_not_allowed", "{bad}");
    }

    let started = gateway
        .start(Some(supervisor.clone()), "127.0.0.1", 0)
        .await
        .expect("session starts");
    assert_eq!(started.state, "active");
    let url = started.url.clone().unwrap();
    assert!(url.starts_with("http://127.0.0.1:") && url.contains("/u/"));
    let token = url
        .trim_end_matches('/')
        .rsplit('/')
        .next()
        .unwrap()
        .to_string();
    assert_eq!(token.len(), 64, "256-bit token");
    assert!(started.qr_svg.as_deref().unwrap_or("").contains("<svg"));
    assert!(
        gateway
            .start(Some(supervisor.clone()), "127.0.0.1", 0)
            .await
            .is_err(),
        "one session at a time"
    );

    // A wrong token and the desktop API's routes reveal nothing.
    let port = started.port.unwrap();
    let base = format!("http://127.0.0.1:{port}");
    for path in [
        format!("/u/{}/", "0".repeat(64)),
        "/v1/assets".to_string(),
        "/v1/health".to_string(),
        "/".to_string(),
    ] {
        let response = reqwest::get(format!("{base}{path}")).await.unwrap();
        assert_eq!(response.status().as_u16(), 404, "{path}");
        assert_eq!(
            response.text().await.unwrap(),
            "This upload link is not active."
        );
    }
    let page = reqwest::get(&url).await.unwrap();
    assert_eq!(page.status().as_u16(), 200);

    // The phone sends a clip, the same clip again, a disguised file, and a document.
    let (status, body) = put(&url, "..%2F..%2Fphone%20clip.mp4", clip.clone()).await;
    assert_eq!(status, 200, "{body}");
    let (status, _) = put(&url, "phone%20clip.mp4", clip.clone()).await;
    assert_eq!(status, 200);
    let (status, body) = put(
        &url,
        "fake.mp4",
        b"<html>not a video at all</html>".to_vec(),
    )
    .await;
    assert_eq!(status, 415, "{body}");
    let (status, _) = put(&url, "notes.pdf", b"%PDF-1.7".to_vec()).await;
    assert_eq!(status, 415);

    let done = wait_for(&gateway, |s| {
        s.uploads.len() == 3
            && s.uploads
                .iter()
                .all(|u| !matches!(u.status.as_str(), "receiving" | "importing"))
    })
    .await;
    let outcomes: Vec<(&str, &str)> = done
        .uploads
        .iter()
        .map(|u| (u.name.as_str(), u.status.as_str()))
        .collect();
    assert_eq!(
        outcomes,
        vec![
            ("phone clip.mp4", "imported"),
            ("phone clip.mp4", "duplicate"),
            ("fake.mp4", "rejected"),
        ]
    );
    let asset_id = done.uploads[0].asset_id.clone().unwrap();
    let asset = supervisor
        .request(
            reqwest::Method::GET,
            &format!("/v1/assets/{asset_id}"),
            None,
            None,
        )
        .await
        .unwrap();
    assert_eq!(asset["source_kind"], "phone_upload");
    assert_eq!(asset["import_mode"], "managed");
    assert_eq!(asset["original_name"], "phone clip.mp4");
    let assets = supervisor
        .request(reqwest::Method::GET, "/v1/assets", None, None)
        .await
        .unwrap();
    assert_eq!(
        assets.as_array().unwrap().len(),
        1,
        "the fake never entered the library"
    );

    // Closing the screen ends the session: the page and port are gone, staging is empty.
    gateway.stop().await;
    let ended = gateway.status();
    assert_eq!(ended.state, "ended");
    assert!(ended.url.is_none() && ended.qr_svg.is_none());
    assert!(
        reqwest::get(&url).await.is_err(),
        "gateway must be unreachable after closing"
    );
    let leftovers: Vec<_> = walk(&staging_root);
    assert!(leftovers.is_empty(), "staging left behind: {leftovers:?}");

    supervisor.stop().await;
}

fn walk(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(entries) = std::fs::read_dir(root) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                out.extend(walk(&path));
            } else {
                out.push(path);
            }
        }
    }
    out
}

#[tokio::test(flavor = "multi_thread")]
async fn gateway_is_not_listening_before_a_session() {
    let dir = tempfile::tempdir().unwrap();
    let gateway = PhoneGateway::new(PhoneConfig {
        command: worker_command(),
        staging_root: dir.path().join("phone"),
        session_seconds: 600,
        allow_loopback: true,
    });
    assert_eq!(gateway.status().state, "idle");
    assert!(gateway.status().url.is_none());
    // Without a worker the session still opens (uploads would wait for import), and
    // the phone's "I'm done" ends it.
    let started = gateway.start(None, "127.0.0.1", 0).await.unwrap();
    let url = started.url.unwrap();
    let finish = reqwest::Client::new()
        .post(format!("{url}finish"))
        .send()
        .await
        .unwrap();
    assert_eq!(finish.status().as_u16(), 200);
    let ended = wait_for(&gateway, |s| s.state == "ended").await;
    assert_eq!(ended.ended_reason.as_deref(), Some("finished_on_phone"));
    assert!(reqwest::get(&url).await.is_err());
}
