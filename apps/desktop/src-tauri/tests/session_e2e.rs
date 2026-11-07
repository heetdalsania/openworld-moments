// SPDX-License-Identifier: AGPL-3.0-or-later
//! End-to-end session timeline path (M13), against the real worker and FFmpeg, using
//! only routes the UI may call: import three clips (two cut from one master so the
//! second repeats the end of the first), group them into a session, find the repeated
//! footage, then reorder and override exactly as the session view does. Checks that
//! every layout the player builds on is consistent and that sources are untouched.
//!
//! Requires the repository's Python environment (`uv sync --all-packages`) and
//! FFmpeg. Without FFmpeg the test is skipped, unless `OWM_REQUIRE_FFMPEG=1` (CI).
//!
//! Run: `cargo test -p openworld-moments-desktop --test session_e2e`

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use openworld_moments_desktop_lib::media::api_route_allowed;
use openworld_moments_desktop_lib::worker::{Supervisor, SupervisorConfig, WorkerCommand};
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

fn run_ffmpeg(ffmpeg: &Path, args: Vec<&str>) {
    let status = Command::new(ffmpeg)
        .args(["-hide_banner", "-loglevel", "error", "-nostdin", "-y"])
        .args(&args)
        .status()
        .expect("ffmpeg runs");
    assert!(status.success(), "ffmpeg {args:?}");
}

/// Argument groups joined into one argv (each group a slice, so lengths may differ).
fn argv<'a>(parts: &[&[&'a str]]) -> Vec<&'a str> {
    parts.concat()
}

const X264: [&str; 6] = [
    "-c:v",
    "libx264",
    "-preset",
    "ultrafast",
    "-pix_fmt",
    "yuv420p",
];

/// Chaotic video (every frame differs) and a modulated tone, like the M12 fixtures.
fn make_clips(ffmpeg: &Path, dir: &Path) -> [PathBuf; 3] {
    let master = dir.join("master.mkv");
    let master_s = master.to_str().unwrap();
    run_ffmpeg(
        ffmpeg,
        argv(&[
            &[
                "-f",
                "lavfi",
                "-i",
                "life=s=320x180:rate=30:ratio=0.3:seed=7:mold=10",
            ],
            &[
                "-f",
                "lavfi",
                "-i",
                "aevalsrc='0.4*sin(2*PI*440*t)*(0.55+0.45*sin(2*PI*0.37*t)*sin(2*PI*1.13*t))':s=48000",
            ],
            &["-t", "30"],
            &X264,
            &["-crf", "18", "-c:a", "aac", master_s],
        ]),
    );
    let captures = dir.join("Captures");
    std::fs::create_dir(&captures).unwrap();
    let cut = |name: &str, start: &str, length: &str, created: &str| {
        let target = captures.join(name);
        run_ffmpeg(
            ffmpeg,
            argv(&[
                &["-ss", start, "-t", length, "-i", master_s],
                &X264,
                &[
                    "-c:a",
                    "aac",
                    "-metadata",
                    &format!("creation_time={created}"),
                ],
                &[target.to_str().unwrap()],
            ]),
        );
        target
    };
    // A: master 0-20 s. B: master 15-30 s, so its first 5 s repeat A's end.
    let a = cut("part one.mp4", "0", "20", "2026-11-01T20:00:00Z");
    let b = cut("part two.mp4", "15", "15", "2026-11-01T20:00:15Z");
    // C: unrelated footage shortly after B.
    let c = captures.join("part three.mp4");
    run_ffmpeg(
        ffmpeg,
        argv(&[
            &[
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=30:duration=6",
            ],
            &[
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=330:sample_rate=48000:duration=6",
            ],
            &X264,
            &["-c:a", "aac", "-shortest"],
            &["-metadata", "creation_time=2026-11-01T20:00:40Z"],
            &[c.to_str().unwrap()],
        ]),
    );
    [a, b, c]
}

async fn ui(supervisor: &Supervisor, method: &str, path: &str, body: Option<Value>) -> Value {
    assert!(api_route_allowed(method, path), "UI route {method} {path}");
    let method = match method {
        "GET" => reqwest::Method::GET,
        "PUT" => reqwest::Method::PUT,
        _ => reqwest::Method::POST,
    };
    supervisor
        .request(method, path, body.as_ref(), None)
        .await
        .unwrap_or_else(|e| panic!("{path}: {e:?}"))
}

async fn finished(supervisor: &Supervisor, job: Value) -> Value {
    let id = job["id"].as_str().unwrap().to_string();
    let job = timeout(Duration::from_secs(180), async {
        loop {
            let job = ui(supervisor, "GET", &format!("/v1/jobs/{id}"), None).await;
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
    .expect("job finishes");
    assert_eq!(job["state"], "ready", "{job}");
    job
}

fn ids(session: &Value) -> Vec<String> {
    session["assets"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| m["asset_id"].as_str().unwrap().to_string())
        .collect()
}

fn overlap(session: &Value, index: usize) -> i64 {
    session["assets"][index]["overlap_with_previous_ms"]
        .as_i64()
        .unwrap_or(0)
}

/// The contract the player's mapping relies on: order indexes 0..n, starts never
/// decreasing, overlaps within the clip, and an applied overlap placing the clip that
/// much before the previous end. (Without one, a clip may start later, after a real
/// pause the virtual timeline does not play, or keep its capture-time position.)
fn assert_layout(session: &Value) {
    let members = session["assets"].as_array().unwrap();
    let (mut start_before, mut end) = (0i64, 0i64);
    for (i, m) in members.iter().enumerate() {
        assert_eq!(m["order_index"].as_u64(), Some(i as u64), "{session}");
        let start = m["session_start_ms"].as_i64().unwrap();
        let duration = m["duration_ms"].as_i64().unwrap();
        let overlap = m["overlap_with_previous_ms"].as_i64().unwrap_or(0);
        assert!(start >= start_before, "{session}");
        assert!((0..=duration).contains(&overlap), "{session}");
        if i > 0 && overlap > 0 {
            assert_eq!(start, end - overlap, "{session}");
        }
        start_before = start;
        end = start + duration;
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn group_align_reorder_and_override() {
    let Some(ffmpeg) = ffmpeg() else {
        eprintln!("skipping: FFmpeg not found");
        return;
    };
    let dir = tempfile::tempdir().unwrap();
    let [a_path, b_path, c_path] = make_clips(&ffmpeg, dir.path());
    let originals: Vec<Vec<u8>> = [&a_path, &b_path, &c_path]
        .iter()
        .map(|p| std::fs::read(p).unwrap())
        .collect();

    let config = SupervisorConfig::new(worker_command(), dir.path().join("library"));
    let supervisor = Supervisor::new(config);
    supervisor.start().await.expect("worker starts");

    let job = ui(
        &supervisor,
        "POST",
        "/v1/imports",
        Some(json!({ "paths": [a_path, b_path, c_path], "mode": "reference", "recursive": false })),
    )
    .await;
    let job = finished(&supervisor, job).await;
    // Items name the requested path by its index in `paths`.
    let asset_of = |source: u64| -> String {
        job["result"]["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|i| i["source"].as_u64() == Some(source))
            .and_then(|i| i["asset_id"].as_str())
            .unwrap_or_else(|| panic!("path {source} imported: {job}"))
            .to_string()
    };
    let (a, b, c) = (asset_of(0), asset_of(1), asset_of(2));

    // Group, as "Group clips into sessions" does.
    let job = ui(
        &supervisor,
        "POST",
        "/v1/sessions/recompute",
        Some(json!({})),
    )
    .await;
    finished(&supervisor, job).await;
    let sessions = ui(&supervisor, "GET", "/v1/sessions?limit=200", None).await;
    let sessions = sessions.as_array().unwrap();
    assert_eq!(sessions.len(), 1, "{sessions:?}");
    let id = sessions[0]["id"].as_str().unwrap().to_string();
    let path = format!("/v1/sessions/{id}");
    let session = ui(&supervisor, "GET", &path, None).await;
    assert_eq!(ids(&session), [a.as_str(), b.as_str(), c.as_str()]);

    // Find repeated footage, as "Find repeated footage" does.
    let job = ui(&supervisor, "POST", "/v1/sessions/align", Some(json!({}))).await;
    finished(&supervisor, job).await;
    let session = ui(&supervisor, "GET", &path, None).await;
    assert_layout(&session);
    let found = overlap(&session, 1);
    assert!(
        (found - 5000).abs() <= 200,
        "B repeats ~5 s of A: {session}"
    );
    assert!(
        session["assets"][1]["alignment_confidence"]
            .as_f64()
            .unwrap()
            > 0.5
    );
    assert_eq!(overlap(&session, 2), 0, "C repeats nothing");
    let overlaps = ui(&supervisor, "GET", &format!("{path}/overlaps"), None).await;
    let pair = overlaps
        .as_array()
        .unwrap()
        .iter()
        .find(|o| o["asset_a"] == a.as_str() && o["asset_b"] == b.as_str())
        .unwrap_or_else(|| panic!("A→B overlap listed: {overlaps}"));
    assert_eq!(pair["applied"]["source"], "auto");

    // Reorder, as "Move earlier" does: out of capture order, clips play end to end.
    let reordered = ui(
        &supervisor,
        "POST",
        &format!("{path}/order"),
        Some(json!({ "asset_ids": [a, c, b] })),
    )
    .await;
    assert_eq!(ids(&reordered), [a.as_str(), c.as_str(), b.as_str()]);
    assert_eq!(reordered["review_state"], "corrected");
    assert_layout(&reordered);
    assert_eq!((overlap(&reordered, 1), overlap(&reordered, 2)), (0, 0));
    // Back in capture order, the match applies again without recomputation.
    let restored = ui(
        &supervisor,
        "POST",
        &format!("{path}/order"),
        Some(json!({ "asset_ids": [a, b, c] })),
    )
    .await;
    assert_layout(&restored);
    assert_eq!(overlap(&restored, 1), found);

    // Override, as "Not repeated footage" and "Use automatic match" do.
    let none = ui(
        &supervisor,
        "PUT",
        &format!("{path}/overlaps/{b}"),
        Some(json!({ "overlap_ms": 0 })),
    )
    .await;
    assert_layout(&none);
    assert_eq!(overlap(&none, 1), 0);
    let auto = ui(
        &supervisor,
        "PUT",
        &format!("{path}/overlaps/{b}"),
        Some(json!({ "overlap_ms": null })),
    )
    .await;
    assert_layout(&auto);
    assert_eq!(overlap(&auto, 1), found);

    // Every correction is logged.
    let log = ui(&supervisor, "GET", &format!("{path}/corrections"), None).await;
    assert!(log.as_array().unwrap().len() >= 2, "{log}");

    supervisor.stop().await;
    for (path, original) in [&a_path, &b_path, &c_path].iter().zip(&originals) {
        assert_eq!(
            &std::fs::read(path).unwrap(),
            original,
            "sources are never modified"
        );
    }
}
