// SPDX-License-Identifier: AGPL-3.0-or-later
//! Watched folders (M07): native events plus reconciliation scans, file
//! stabilization, and reports of stable files to the worker, which decides
//! whether to import them. See docs/architecture/watched-folders.md.

pub mod fsprobe;
pub mod patterns;
pub mod service;
pub mod sink;
pub mod stabilizer;

pub use service::{FolderStatus, WatchConfig, WatchService};
pub use sink::{FolderConfig, Sink, SinkError, WorkerSink};
pub use stabilizer::Meta;
