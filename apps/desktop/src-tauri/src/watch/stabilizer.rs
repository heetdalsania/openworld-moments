// SPDX-License-Identifier: AGPL-3.0-or-later
//! File stabilization (spec 8.1.2): a file is a candidate only after its size and
//! modification time stayed unchanged for `stable_for`. Pure and clock-injected,
//! so it is tested without sleeping.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The version of a file the worker identifies it by.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Meta {
    pub size: u64,
    pub mtime_ns: i128,
}

#[derive(Debug)]
pub struct Stabilizer {
    stable_for: Duration,
    pending: HashMap<PathBuf, (Meta, Instant)>,
}

impl Stabilizer {
    pub fn new(stable_for: Duration) -> Self {
        Self {
            stable_for,
            pending: HashMap::new(),
        }
    }

    /// Record the current metadata of a file. Any change restarts its timer; seeing
    /// the same metadata again (repeated OS events, rescans) does not.
    pub fn observe(&mut self, path: &Path, meta: Meta, now: Instant) {
        match self.pending.get_mut(path) {
            Some((known, _)) if *known == meta => {}
            Some(entry) => *entry = (meta, now),
            None => {
                self.pending.insert(path.to_path_buf(), (meta, now));
            }
        }
    }

    pub fn forget(&mut self, path: &Path) {
        self.pending.remove(path);
    }

    pub fn clear(&mut self) {
        self.pending.clear();
    }

    pub fn paths(&self) -> Vec<PathBuf> {
        self.pending.keys().cloned().collect()
    }

    pub fn len(&self) -> usize {
        self.pending.len()
    }

    pub fn is_empty(&self) -> bool {
        self.pending.is_empty()
    }

    /// Remove and return files unchanged for at least `stable_for`.
    pub fn take_due(&mut self, now: Instant) -> Vec<(PathBuf, Meta)> {
        let due: Vec<PathBuf> = self
            .pending
            .iter()
            .filter(|(_, (_, since))| now.saturating_duration_since(*since) >= self.stable_for)
            .map(|(p, _)| p.clone())
            .collect();
        let mut out: Vec<(PathBuf, Meta)> = due
            .into_iter()
            .filter_map(|p| self.pending.remove(&p).map(|(m, _)| (p, m)))
            .collect();
        out.sort_by(|a, b| a.0.cmp(&b.0));
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const STABLE: Duration = Duration::from_secs(10);

    fn meta(size: u64) -> Meta {
        Meta { size, mtime_ns: 7 }
    }

    #[test]
    fn growing_file_is_not_due_until_it_stops() {
        let t0 = Instant::now();
        let mut s = Stabilizer::new(STABLE);
        let path = Path::new("/w/clip.mp4");
        for (i, size) in [100, 200, 300].into_iter().enumerate() {
            s.observe(path, meta(size), t0 + Duration::from_secs(5 * i as u64));
        }
        // Last change at t0+10s: not due at t0+19s, due at t0+20s.
        assert!(s.take_due(t0 + Duration::from_secs(19)).is_empty());
        assert_eq!(
            s.take_due(t0 + Duration::from_secs(20)),
            vec![(path.to_path_buf(), meta(300))]
        );
        assert!(s.is_empty());
    }

    #[test]
    fn repeated_events_do_not_restart_the_timer() {
        let t0 = Instant::now();
        let mut s = Stabilizer::new(STABLE);
        let path = Path::new("/w/clip.mp4");
        for i in 0..1000 {
            s.observe(path, meta(100), t0 + Duration::from_millis(i));
        }
        assert_eq!(s.len(), 1);
        assert_eq!(s.take_due(t0 + STABLE).len(), 1);
    }

    #[test]
    fn mtime_change_alone_restarts_the_timer() {
        let t0 = Instant::now();
        let mut s = Stabilizer::new(STABLE);
        let path = Path::new("/w/clip.mp4");
        s.observe(path, meta(100), t0);
        s.observe(
            path,
            Meta {
                size: 100,
                mtime_ns: 8,
            },
            t0 + Duration::from_secs(9),
        );
        assert!(s.take_due(t0 + STABLE).is_empty());
        s.forget(path);
        assert!(s.take_due(t0 + STABLE * 3).is_empty());
    }
}
