// SPDX-License-Identifier: AGPL-3.0-or-later
//! The watch loop: native filesystem events plus a periodic reconciliation scan
//! feed a stabilizer; stable, readable files are reported to the worker, which
//! decides whether to import them.
//!
//! * Events only mark paths as "maybe changed". Every path is re-checked on each
//!   tick, so lost or coalesced OS events cannot cause a wrong import, and an
//!   event storm for one file is one entry.
//! * A full scan runs at start (files added while the app was closed), when a
//!   folder becomes available again, and every `reconcile_every`.
//! * An unavailable folder (unplugged drive, offline share) is checked again
//!   with exponential backoff; the change is logged and reported once, and no
//!   events, scans, or imports happen meanwhile.
//! * Cloud placeholders that are not on this computer are never opened.
//! * Disabled folders are not watched at all. Nothing is ever written to,
//!   moved, or deleted from a watched folder.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use serde::Serialize;
use serde_json::json;
use tokio::sync::{Notify, mpsc};

use super::fsprobe::{self, FileState};
use super::patterns::is_candidate;
use super::sink::{FolderConfig, Sink, SinkError};
use super::stabilizer::{Meta, Stabilizer};

#[derive(Debug, Clone)]
pub struct WatchConfig {
    /// How often pending files are re-checked.
    pub tick: Duration,
    /// Unchanged size and mtime for this long make a file stable (spec 8.1.2: 10 s).
    pub stable_for: Duration,
    /// Full reconciliation scan interval.
    pub reconcile_every: Duration,
    /// How often the folder list is re-read from the worker (also on `refresh`).
    pub reload_every: Duration,
    /// First and largest delay between checks of an unavailable folder.
    pub backoff_base: Duration,
    pub backoff_max: Duration,
    pub max_scan_entries: usize,
    pub max_depth: usize,
}

impl Default for WatchConfig {
    fn default() -> Self {
        Self {
            tick: Duration::from_secs(1),
            stable_for: Duration::from_secs(10),
            reconcile_every: Duration::from_secs(15 * 60),
            reload_every: Duration::from_secs(60),
            backoff_base: Duration::from_secs(15),
            backoff_max: Duration::from_secs(15 * 60),
            max_scan_entries: 100_000,
            max_depth: 32,
        }
    }
}

/// What the UI shows per folder (merged with the worker's `WatchedFolder`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FolderStatus {
    pub id: i64,
    /// `starting`, `watching`, `scanning-only` (no native events), or `unavailable`.
    pub state: &'static str,
    /// Files waiting to become stable.
    pub pending: usize,
    /// Cloud placeholders not yet downloaded to this computer.
    pub cloud_only: usize,
    /// Stable files reported to the worker since the app started.
    pub reported: usize,
    /// Reports the worker refused.
    pub rejected: usize,
    /// Milliseconds until an unavailable folder is checked again.
    pub next_check_ms: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Availability {
    Unknown,
    Available,
    Unavailable { attempts: u32, next_check: Instant },
}

struct Folder {
    cfg: FolderConfig,
    /// Canonical root, so event paths (e.g. /private/var vs /var on macOS) still match.
    real_root: Option<PathBuf>,
    watcher: Option<RecommendedWatcher>,
    watcher_failed: bool,
    stabilizer: Stabilizer,
    reported: HashMap<PathBuf, Meta>,
    cloud_only: HashSet<PathBuf>,
    availability: Availability,
    last_reconcile: Option<Instant>,
    rejected: usize,
}

type Event = (i64, PathBuf);

/// Cheap to clone; clones share the loop's status and refresh signal.
#[derive(Clone)]
pub struct WatchService<S: Sink> {
    sink: Arc<S>,
    cfg: WatchConfig,
    refresh: Arc<Notify>,
    stop: Arc<Notify>,
    status: Arc<StdMutex<Vec<FolderStatus>>>,
}

impl<S: Sink> WatchService<S> {
    pub fn new(sink: S, cfg: WatchConfig) -> Self {
        Self {
            sink: Arc::new(sink),
            cfg,
            refresh: Arc::new(Notify::new()),
            stop: Arc::new(Notify::new()),
            status: Arc::new(StdMutex::new(Vec::new())),
        }
    }

    /// Re-read the folder list now (after the UI added, changed, or removed one).
    pub fn refresh(&self) {
        self.refresh.notify_one();
    }

    pub fn stop(&self) {
        self.stop.notify_one();
    }

    pub fn status(&self) -> Vec<FolderStatus> {
        self.status.lock().map(|s| s.clone()).unwrap_or_default()
    }

    /// Run until `stop` is called.
    pub async fn run(self) {
        let (tx, mut rx) = mpsc::unbounded_channel::<Event>();
        let mut folders: HashMap<i64, Folder> = HashMap::new();
        let mut last_reload: Option<Instant> = None;
        let mut reload = true;
        loop {
            if reload || last_reload.is_none_or(|t| t.elapsed() >= self.cfg.reload_every) {
                if let Ok(list) = self.sink.folders().await {
                    self.apply(&mut folders, list);
                    last_reload = Some(Instant::now());
                }
                reload = false;
            }
            while let Ok((id, path)) = rx.try_recv() {
                if let Some(folder) = folders.get_mut(&id) {
                    self.on_event(folder, &path);
                }
            }
            for folder in folders.values_mut() {
                self.tend(folder, &tx).await;
            }
            self.publish(&folders);
            tokio::select! {
                _ = tokio::time::sleep(self.cfg.tick) => {}
                _ = self.refresh.notified() => reload = true,
                _ = self.stop.notified() => break,
            }
        }
    }

    fn apply(&self, folders: &mut HashMap<i64, Folder>, list: Vec<FolderConfig>) {
        let wanted: HashMap<i64, FolderConfig> = list
            .into_iter()
            .filter(|f| f.enabled)
            .map(|f| (f.id, f))
            .collect();
        folders.retain(|id, _| wanted.contains_key(id)); // dropping a watcher stops it
        for (id, cfg) in wanted {
            match folders.get_mut(&id) {
                Some(existing) if existing.cfg == cfg => {}
                Some(existing) => {
                    // Settings changed: start over with a fresh watcher and a full scan.
                    *existing = self.new_folder(cfg);
                }
                None => {
                    folders.insert(id, self.new_folder(cfg));
                }
            }
        }
    }

    fn new_folder(&self, cfg: FolderConfig) -> Folder {
        Folder {
            real_root: None,
            watcher: None,
            watcher_failed: false,
            stabilizer: Stabilizer::new(self.cfg.stable_for),
            reported: HashMap::new(),
            cloud_only: HashSet::new(),
            availability: Availability::Unknown,
            last_reconcile: None,
            rejected: 0,
            cfg,
        }
    }

    fn relative(folder: &Folder, path: &Path) -> Option<String> {
        fsprobe::relative(&folder.cfg.path, path).or_else(|| {
            folder
                .real_root
                .as_deref()
                .and_then(|root| fsprobe::relative(root, path))
        })
    }

    fn on_event(&self, folder: &mut Folder, path: &Path) {
        if !matches!(folder.availability, Availability::Available) {
            return;
        }
        if folder.cfg.recursive && path.is_dir() {
            // A folder moved in: look at everything inside it.
            for file in fsprobe::walk(path, true, self.cfg.max_scan_entries, self.cfg.max_depth) {
                self.observe(folder, &file, Instant::now());
            }
        } else {
            self.observe(folder, path, Instant::now());
        }
    }

    fn observe(&self, folder: &mut Folder, path: &Path, now: Instant) {
        let Some(rel) = Self::relative(folder, path) else {
            return;
        };
        if !folder.cfg.recursive && rel.contains('/') {
            return;
        }
        if !is_candidate(&rel, &folder.cfg.include, &folder.cfg.exclude) {
            return;
        }
        match fsprobe::file_state(path) {
            FileState::Local(meta) => {
                folder.cloud_only.remove(path);
                if folder.reported.get(path) != Some(&meta) {
                    folder.stabilizer.observe(path, meta, now);
                }
            }
            FileState::CloudOnly => {
                folder.stabilizer.forget(path);
                folder.cloud_only.insert(path.to_path_buf());
            }
            FileState::Absent => {
                folder.stabilizer.forget(path);
                folder.cloud_only.remove(path);
            }
        }
    }

    fn backoff(&self, attempts: u32) -> Duration {
        let factor = 2u32.saturating_pow(attempts.saturating_sub(1).min(20));
        self.cfg
            .backoff_base
            .saturating_mul(factor)
            .min(self.cfg.backoff_max)
    }

    async fn tend(&self, folder: &mut Folder, tx: &mpsc::UnboundedSender<Event>) {
        let now = Instant::now();
        if let Availability::Unavailable { next_check, .. } = folder.availability
            && now < next_check
        {
            return;
        }
        if let Err(kind) = fsprobe::folder_available(&folder.cfg.path) {
            self.mark_unavailable(folder, &kind).await;
            return;
        }
        if !matches!(folder.availability, Availability::Available) {
            if matches!(folder.availability, Availability::Unavailable { .. }) {
                eprintln!("watch: folder {} is available again", folder.cfg.id);
            }
            folder.availability = Availability::Available;
            folder.real_root = std::fs::canonicalize(&folder.cfg.path).ok();
            folder.last_reconcile = None; // rescan everything it may have missed
        }
        if folder.watcher.is_none() && !folder.watcher_failed {
            match self.start_watcher(&folder.cfg, tx) {
                Ok(w) => folder.watcher = Some(w),
                Err(_) => {
                    folder.watcher_failed = true; // scans still find new files
                    eprintln!(
                        "watch: native events unavailable for folder {}; scanning only",
                        folder.cfg.id
                    );
                }
            }
        }
        if folder
            .last_reconcile
            .is_none_or(|t| now.duration_since(t) >= self.cfg.reconcile_every)
        {
            let files = fsprobe::walk(
                &folder.cfg.path,
                folder.cfg.recursive,
                self.cfg.max_scan_entries,
                self.cfg.max_depth,
            );
            for file in files {
                self.observe(folder, &file, now);
            }
            folder.last_reconcile = Some(now);
            let _ = self.sink.report_scan(folder.cfg.id, true, true, None).await;
        }
        self.stabilize(folder).await;
    }

    async fn mark_unavailable(&self, folder: &mut Folder, kind: &str) {
        let attempts = match folder.availability {
            Availability::Unavailable { attempts, .. } => attempts + 1,
            _ => {
                // Report and log the change once, not on every retry.
                eprintln!(
                    "watch: folder {} is unavailable ({kind}); retrying with backoff",
                    folder.cfg.id
                );
                let error = json!({
                    "code": "watch.folder_unavailable",
                    "message": "The folder cannot be read. It may be on a disconnected drive or an offline location.",
                    "retryable": true,
                    "details": { "reason": kind },
                });
                let _ = self
                    .sink
                    .report_scan(folder.cfg.id, false, false, Some(error))
                    .await;
                1
            }
        };
        folder.watcher = None;
        folder.watcher_failed = false;
        folder.stabilizer.clear();
        folder.cloud_only.clear();
        folder.availability = Availability::Unavailable {
            attempts,
            next_check: Instant::now() + self.backoff(attempts),
        };
    }

    fn start_watcher(
        &self,
        cfg: &FolderConfig,
        tx: &mpsc::UnboundedSender<Event>,
    ) -> notify::Result<RecommendedWatcher> {
        let tx = tx.clone();
        let id = cfg.id;
        let mut watcher =
            notify::recommended_watcher(move |res: notify::Result<notify::Event>| {
                if let Ok(event) = res {
                    for path in event.paths {
                        let _ = tx.send((id, path));
                    }
                }
            })?;
        let mode = if cfg.recursive {
            RecursiveMode::Recursive
        } else {
            RecursiveMode::NonRecursive
        };
        watcher.watch(&cfg.path, mode)?;
        Ok(watcher)
    }

    async fn stabilize(&self, folder: &mut Folder) {
        let now = Instant::now();
        for path in folder.stabilizer.paths() {
            self.observe(folder, &path, now); // re-check: a change restarts the timer
        }
        for (path, meta) in folder.stabilizer.take_due(now) {
            if !fsprobe::readable(&path) {
                folder.stabilizer.observe(&path, meta, Instant::now());
                continue; // still held by the program writing it
            }
            let Some(rel) = Self::relative(folder, &path) else {
                continue;
            };
            match self.sink.report_file(folder.cfg.id, &rel, meta).await {
                Ok(_) => {
                    folder.reported.insert(path, meta);
                }
                Err(SinkError::Unavailable(_)) => {
                    folder.stabilizer.observe(&path, meta, Instant::now()); // retry later
                }
                Err(SinkError::Rejected(_)) => {
                    folder.rejected += 1;
                    folder.reported.insert(path, meta); // do not repeat a refused report
                }
            }
        }
    }

    fn publish(&self, folders: &HashMap<i64, Folder>) {
        let mut out: Vec<FolderStatus> = folders
            .values()
            .map(|f| FolderStatus {
                id: f.cfg.id,
                state: match f.availability {
                    Availability::Unknown => "starting",
                    Availability::Unavailable { .. } => "unavailable",
                    Availability::Available if f.watcher.is_some() => "watching",
                    Availability::Available => "scanning-only",
                },
                pending: f.stabilizer.len(),
                cloud_only: f.cloud_only.len(),
                reported: f.reported.len(),
                rejected: f.rejected,
                next_check_ms: match f.availability {
                    Availability::Unavailable { next_check, .. } => Some(
                        next_check
                            .saturating_duration_since(Instant::now())
                            .as_millis() as u64,
                    ),
                    _ => None,
                },
            })
            .collect();
        out.sort_by_key(|s| s.id);
        if let Ok(mut status) = self.status.lock() {
            *status = out;
        }
    }
}
