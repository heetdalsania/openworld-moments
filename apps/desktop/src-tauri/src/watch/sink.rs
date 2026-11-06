// SPDX-License-Identifier: AGPL-3.0-or-later
//! Where the watcher sends what it finds. The worker owns watched-folder state;
//! a `Sink` is the narrow interface to it (and a fake in tests).

use std::future::Future;
use std::path::PathBuf;

use serde::Deserialize;
use serde_json::{Value, json};

use super::stabilizer::Meta;
use crate::worker::{Supervisor, SupervisorError};

/// The parts of a contract `WatchedFolder` the host needs.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct FolderConfig {
    pub id: i64,
    pub path: PathBuf,
    pub recursive: bool,
    pub include: Vec<String>,
    pub exclude: Vec<String>,
    pub enabled: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SinkError {
    /// The worker is not reachable right now; try again later.
    Unavailable(String),
    /// The worker refused the report (e.g. the folder was removed or disabled).
    Rejected(String),
}

pub trait Sink: Send + Sync + 'static {
    fn folders(&self) -> impl Future<Output = Result<Vec<FolderConfig>, SinkError>> + Send;
    /// Report a stable file; returns the worker's `WatchedFileDecision.action`.
    fn report_file(
        &self,
        folder_id: i64,
        relative_path: &str,
        meta: Meta,
    ) -> impl Future<Output = Result<String, SinkError>> + Send;
    fn report_scan(
        &self,
        folder_id: i64,
        available: bool,
        scanned: bool,
        error: Option<Value>,
    ) -> impl Future<Output = Result<(), SinkError>> + Send;
}

/// The real sink: the worker's `/v1/watched-folders` API.
#[derive(Clone)]
pub struct WorkerSink(pub Supervisor);

fn sink_error(err: SupervisorError) -> SinkError {
    match err {
        SupervisorError::Http { status, body } if (400..500).contains(&status) => {
            SinkError::Rejected(body["code"].as_str().unwrap_or("rejected").to_string())
        }
        other => SinkError::Unavailable(other.to_string()),
    }
}

impl Sink for WorkerSink {
    async fn folders(&self) -> Result<Vec<FolderConfig>, SinkError> {
        let body = self
            .0
            .request(reqwest::Method::GET, "/v1/watched-folders", None, None)
            .await
            .map_err(sink_error)?;
        serde_json::from_value(body).map_err(|e| SinkError::Unavailable(e.to_string()))
    }

    async fn report_file(
        &self,
        folder_id: i64,
        relative_path: &str,
        meta: Meta,
    ) -> Result<String, SinkError> {
        let body = json!({
            "relative_path": relative_path,
            "size_bytes": meta.size,
            "mtime_ns": meta.mtime_ns as i64,
        });
        let answer = self
            .0
            .request(
                reqwest::Method::POST,
                &format!("/v1/watched-folders/{folder_id}/files"),
                Some(&body),
                None,
            )
            .await
            .map_err(sink_error)?;
        Ok(answer["action"].as_str().unwrap_or("unknown").to_string())
    }

    async fn report_scan(
        &self,
        folder_id: i64,
        available: bool,
        scanned: bool,
        error: Option<Value>,
    ) -> Result<(), SinkError> {
        let mut body = json!({ "available": available, "scanned": scanned });
        if let Some(error) = error {
            body["error"] = error;
        }
        self.0
            .request(
                reqwest::Method::POST,
                &format!("/v1/watched-folders/{folder_id}/scans"),
                Some(&body),
                None,
            )
            .await
            .map(|_| ())
            .map_err(sink_error)
    }
}
