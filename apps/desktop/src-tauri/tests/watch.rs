// SPDX-License-Identifier: AGPL-3.0-or-later
//! Watched-folder behavior against real folders and native events (M07), with a
//! fake worker sink. Required validation: slow write, rename into folder,
//! duplicate-event storm, restart reconciliation, offline folder backoff.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use openworld_moments_desktop_lib::watch::{
    FolderConfig, Meta, Sink, SinkError, WatchConfig, WatchService,
};
use serde_json::Value;

#[derive(Clone, Default)]
struct FakeSink {
    folders: Arc<Mutex<Vec<FolderConfig>>>,
    reports: Arc<Mutex<Vec<(i64, String, Meta)>>>,
    scans: Arc<Mutex<Vec<(i64, bool, bool)>>>,
}

impl Sink for FakeSink {
    async fn folders(&self) -> Result<Vec<FolderConfig>, SinkError> {
        Ok(self.folders.lock().unwrap().clone())
    }
    async fn report_file(&self, id: i64, rel: &str, meta: Meta) -> Result<String, SinkError> {
        self.reports
            .lock()
            .unwrap()
            .push((id, rel.to_string(), meta));
        Ok("queued".into())
    }
    async fn report_scan(
        &self,
        id: i64,
        available: bool,
        scanned: bool,
        _error: Option<Value>,
    ) -> Result<(), SinkError> {
        self.scans.lock().unwrap().push((id, available, scanned));
        Ok(())
    }
}

impl FakeSink {
    fn reported(&self) -> Vec<String> {
        self.reports
            .lock()
            .unwrap()
            .iter()
            .map(|r| r.1.clone())
            .collect()
    }
}

fn config() -> WatchConfig {
    WatchConfig {
        tick: Duration::from_millis(50),
        stable_for: Duration::from_millis(700), // well above write gaps, even on slow CI
        reconcile_every: Duration::from_secs(3600),
        reload_every: Duration::from_secs(3600),
        backoff_base: Duration::from_millis(200),
        backoff_max: Duration::from_secs(2),
        max_scan_entries: 10_000,
        max_depth: 32,
    }
}

fn folder(id: i64, path: &Path) -> FolderConfig {
    FolderConfig {
        id,
        path: path.to_path_buf(),
        recursive: true,
        include: vec![],
        exclude: vec![".*".into(), "**/.*/**".into()],
        enabled: true,
    }
}

struct Running {
    service: WatchService<FakeSink>,
    task: tokio::task::JoinHandle<()>,
}

impl Running {
    fn start(sink: &FakeSink) -> Self {
        let service = WatchService::new(sink.clone(), config());
        let task = tokio::spawn(service.clone().run());
        Self { service, task }
    }
    async fn stop(self) {
        self.service.stop();
        tokio::time::timeout(Duration::from_secs(5), self.task)
            .await
            .expect("the watch loop stops promptly")
            .expect("the watch loop does not panic");
    }
}

async fn wait_until(what: &str, timeout: Duration, mut done: impl FnMut() -> bool) {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if done() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    panic!("timed out waiting for {what}");
}

fn write(path: &Path, bytes: &[u8]) {
    fs::write(path, bytes).unwrap();
}

#[tokio::test(flavor = "multi_thread")]
async fn slowly_written_file_is_reported_once_after_it_stops_changing() {
    let dir = tempfile::tempdir().unwrap();
    let sink = FakeSink::default();
    sink.folders.lock().unwrap().push(folder(1, dir.path()));
    let run = Running::start(&sink);
    tokio::time::sleep(Duration::from_millis(200)).await; // initial scan done

    let clip = dir.path().join("Capture 01.mp4");
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&clip)
        .unwrap();
    for _ in 0..8 {
        file.write_all(&[0u8; 4096]).unwrap();
        file.flush().unwrap();
        tokio::time::sleep(Duration::from_millis(100)).await; // much faster than stable_for
        assert!(
            sink.reported().is_empty(),
            "reported while still being written"
        );
    }
    drop(file);
    wait_until("the report", Duration::from_secs(5), || {
        !sink.reported().is_empty()
    })
    .await;
    tokio::time::sleep(Duration::from_millis(1000)).await;
    let reports = sink.reports.lock().unwrap().clone();
    assert_eq!(reports.len(), 1, "{reports:?}");
    assert_eq!(reports[0].1, "Capture 01.mp4");
    assert_eq!(reports[0].2.size, 8 * 4096);
    run.stop().await;
    assert_eq!(
        fs::read(&clip).unwrap().len(),
        8 * 4096,
        "the source must not be touched"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn file_renamed_into_the_folder_is_reported() {
    let outside = tempfile::tempdir().unwrap();
    let dir = tempfile::tempdir().unwrap();
    fs::create_dir(dir.path().join("Halo")).unwrap();
    let sink = FakeSink::default();
    sink.folders.lock().unwrap().push(folder(1, dir.path()));
    let run = Running::start(&sink);
    tokio::time::sleep(Duration::from_millis(200)).await;

    let staged = outside.path().join("download.mp4");
    write(&staged, b"finished capture");
    fs::rename(&staged, dir.path().join("Halo").join("moved in.mp4")).unwrap();
    // A whole folder moved in is scanned too.
    let batch = outside.path().join("batch");
    fs::create_dir(&batch).unwrap();
    write(&batch.join("a.mkv"), b"aaa");
    fs::rename(&batch, dir.path().join("batch")).unwrap();

    wait_until("both reports", Duration::from_secs(5), || {
        sink.reported().len() == 2
    })
    .await;
    let mut got = sink.reported();
    got.sort();
    assert_eq!(
        got,
        vec!["Halo/moved in.mp4".to_string(), "batch/a.mkv".to_string()]
    );
    run.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn event_storm_for_one_file_is_one_report() {
    let dir = tempfile::tempdir().unwrap();
    let clip = dir.path().join("clip.mp4");
    write(&clip, b"version one");
    let sink = FakeSink::default();
    sink.folders.lock().unwrap().push(folder(1, dir.path()));
    let run = Running::start(&sink);
    wait_until("first report", Duration::from_secs(5), || {
        sink.reported().len() == 1
    })
    .await;

    // Many events with unchanged content (opens, attribute touches, rewrites of the same bytes
    // would change mtime; so only open/read here): no new reports.
    for _ in 0..200 {
        let _ = fs::read(&clip).unwrap();
        let _ = OpenOptions::new().append(true).open(&clip).unwrap();
    }
    tokio::time::sleep(Duration::from_millis(1200)).await;
    assert_eq!(sink.reported().len(), 1);

    // A real change is a new version: reported once more after it settles.
    for i in 0..50u8 {
        write(&clip, &[i; 32]);
    }
    wait_until("second report", Duration::from_secs(5), || {
        sink.reported().len() == 2
    })
    .await;
    tokio::time::sleep(Duration::from_millis(1200)).await;
    assert_eq!(sink.reported().len(), 2);
    run.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn restart_finds_files_added_while_stopped() {
    let dir = tempfile::tempdir().unwrap();
    let sink = FakeSink::default();
    sink.folders.lock().unwrap().push(folder(1, dir.path()));
    let run = Running::start(&sink);
    tokio::time::sleep(Duration::from_millis(200)).await;
    run.stop().await;

    fs::create_dir(dir.path().join("sub")).unwrap();
    write(&dir.path().join("sub/missed.mp4"), b"recorded while closed");
    write(&dir.path().join("notes.txt"), b"not a video");
    write(&dir.path().join(".hidden.mp4"), b"excluded");

    let run = Running::start(&sink);
    wait_until("the missed file", Duration::from_secs(5), || {
        !sink.reported().is_empty()
    })
    .await;
    tokio::time::sleep(Duration::from_millis(1000)).await;
    assert_eq!(sink.reported(), vec!["sub/missed.mp4".to_string()]);
    assert!(sink.scans.lock().unwrap().contains(&(1, true, true)));
    run.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn unavailable_folder_backs_off_quietly_and_recovers() {
    let parent = tempfile::tempdir().unwrap();
    let drive: PathBuf = parent.path().join("Capture Drive");
    let sink = FakeSink::default();
    sink.folders.lock().unwrap().push(folder(7, &drive)); // does not exist yet
    let run = Running::start(&sink);

    tokio::time::sleep(Duration::from_millis(1500)).await;
    let scans = sink.scans.lock().unwrap().clone();
    assert_eq!(
        scans,
        vec![(7, false, false)],
        "reported once, not on every retry"
    );
    assert!(sink.reported().is_empty());
    let status = run.service.status();
    assert_eq!(status[0].state, "unavailable");
    assert!(status[0].next_check_ms.is_some());

    fs::create_dir(&drive).unwrap(); // the drive comes back
    write(&drive.join("clip.mp4"), b"captured");
    wait_until("recovery", Duration::from_secs(6), || {
        !sink.reported().is_empty()
    })
    .await;
    assert!(sink.scans.lock().unwrap().contains(&(7, true, true)));
    run.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn disabled_folder_does_no_work() {
    let dir = tempfile::tempdir().unwrap();
    write(&dir.path().join("clip.mp4"), b"captured");
    let sink = FakeSink::default();
    let mut cfg = folder(1, dir.path());
    cfg.enabled = false;
    sink.folders.lock().unwrap().push(cfg);
    let run = Running::start(&sink);
    tokio::time::sleep(Duration::from_millis(900)).await;
    assert!(sink.reported().is_empty());
    assert!(sink.scans.lock().unwrap().is_empty());
    assert!(run.service.status().is_empty());

    sink.folders.lock().unwrap()[0].enabled = true; // enabling takes effect on refresh
    run.service.refresh();
    wait_until("report after enabling", Duration::from_secs(5), || {
        !sink.reported().is_empty()
    })
    .await;
    run.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn non_recursive_folder_ignores_subfolders() {
    let dir = tempfile::tempdir().unwrap();
    fs::create_dir(dir.path().join("sub")).unwrap();
    write(&dir.path().join("sub/deep.mp4"), b"x");
    write(&dir.path().join("top.mp4"), b"y");
    let sink = FakeSink::default();
    let mut cfg = folder(1, dir.path());
    cfg.recursive = false;
    sink.folders.lock().unwrap().push(cfg);
    let run = Running::start(&sink);
    wait_until("top-level report", Duration::from_secs(5), || {
        !sink.reported().is_empty()
    })
    .await;
    write(&dir.path().join("sub/later.mp4"), b"z");
    tokio::time::sleep(Duration::from_millis(1200)).await;
    assert_eq!(sink.reported(), vec!["top.mp4".to_string()]);
    run.stop().await;
}
