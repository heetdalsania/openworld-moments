// SPDX-License-Identifier: AGPL-3.0-or-later
//! Wire formats: the worker's one-line startup message and the job event stream.

use serde::Deserialize;
use serde_json::Value;

/// The single JSON line the worker prints on stdout at startup.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "event", rename_all = "lowercase")]
pub enum StartupLine {
    Ready {
        protocol: u32,
        api_version: u32,
        schema_version: String,
        host: String,
        port: u16,
        pid: u32,
    },
    Error {
        code: String,
        message: String,
    },
}

pub fn parse_startup_line(line: &str) -> Result<StartupLine, String> {
    serde_json::from_str(line.trim()).map_err(|e| format!("malformed startup line: {e}"))
}

/// A job event (contract `JobEvent`). `job` keeps the full contract document.
#[derive(Debug, Clone, PartialEq)]
pub struct JobEvent {
    pub seq: u64,
    pub kind: String,
    pub job_id: String,
    pub state: String,
    pub correlation_id: Option<String>,
    pub raw: Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EventError {
    NotJson,
    MissingField(&'static str),
    UnsupportedSchema(String),
}

impl std::fmt::Display for EventError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotJson => f.write_str("event is not JSON"),
            Self::MissingField(name) => write!(f, "event is missing '{name}'"),
            Self::UnsupportedSchema(v) => write!(f, "unsupported event schema_version {v}"),
        }
    }
}

/// Parse one WebSocket text frame. Malformed frames return an error so the
/// caller can skip them without dropping the connection.
pub fn parse_event(text: &str) -> Result<JobEvent, EventError> {
    let raw: Value = serde_json::from_str(text).map_err(|_| EventError::NotJson)?;
    let version = raw
        .get("schema_version")
        .and_then(Value::as_str)
        .ok_or(EventError::MissingField("schema_version"))?;
    if !version.starts_with("1.") {
        return Err(EventError::UnsupportedSchema(version.to_string()));
    }
    let seq = raw
        .get("seq")
        .and_then(Value::as_u64)
        .filter(|s| *s >= 1)
        .ok_or(EventError::MissingField("seq"))?;
    let kind = raw
        .get("kind")
        .and_then(Value::as_str)
        .ok_or(EventError::MissingField("kind"))?
        .to_string();
    let job = raw.get("job").ok_or(EventError::MissingField("job"))?;
    let job_id = job
        .get("id")
        .and_then(Value::as_str)
        .ok_or(EventError::MissingField("job.id"))?
        .to_string();
    let state = job
        .get("state")
        .and_then(Value::as_str)
        .ok_or(EventError::MissingField("job.state"))?
        .to_string();
    let correlation_id = job
        .get("correlation_id")
        .and_then(Value::as_str)
        .map(str::to_string);
    Ok(JobEvent {
        seq,
        kind,
        job_id,
        state,
        correlation_id,
        raw,
    })
}

/// Result of checking an event's sequence number.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SeqCheck {
    InOrder,
    /// Events were missed; the client should resynchronize with GET /v1/jobs.
    Gap {
        expected: u64,
        got: u64,
    },
    /// Stale or duplicate; drop it.
    Stale,
}

/// Tracks `seq` for one connection. Reset it when the worker restarts.
#[derive(Debug, Default)]
pub struct SeqTracker {
    last: Option<u64>,
}

impl SeqTracker {
    pub fn check(&mut self, seq: u64) -> SeqCheck {
        let result = match self.last {
            None => SeqCheck::InOrder,
            Some(last) if seq == last + 1 => SeqCheck::InOrder,
            Some(last) if seq <= last => return SeqCheck::Stale,
            Some(last) => SeqCheck::Gap {
                expected: last + 1,
                got: seq,
            },
        };
        self.last = Some(seq);
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_and_error_lines() {
        let ready = parse_startup_line(
            r#"{"event":"ready","protocol":1,"api_version":1,"schema_version":"1.1","worker_version":"0.0.0","host":"127.0.0.1","port":4321,"pid":7}"#,
        )
        .unwrap();
        assert!(matches!(ready, StartupLine::Ready { port: 4321, .. }));
        let error =
            parse_startup_line(r#"{"event":"error","code":"worker.port_in_use","message":"busy"}"#)
                .unwrap();
        assert_eq!(
            error,
            StartupLine::Error {
                code: "worker.port_in_use".into(),
                message: "busy".into()
            }
        );
        assert!(parse_startup_line("Traceback (most recent call last):").is_err());
        assert!(parse_startup_line(r#"{"event":"hello"}"#).is_err());
    }

    #[test]
    fn malformed_events_are_rejected_not_fatal() {
        let good = r#"{"schema_version":"1.1","seq":3,"emitted_at":"2026-11-20T05:40:10Z","kind":"progress","job":{"id":"job_X","state":"analyzing","correlation_id":"cor_Y"}}"#;
        let event = parse_event(good).unwrap();
        assert_eq!(
            (
                event.seq,
                event.state.as_str(),
                event.correlation_id.as_deref()
            ),
            (3, "analyzing", Some("cor_Y"))
        );
        for (bad, err) in [
            ("not json", EventError::NotJson),
            (r#"{"seq":1}"#, EventError::MissingField("schema_version")),
            (
                r#"{"schema_version":"2.0","seq":1}"#,
                EventError::UnsupportedSchema("2.0".into()),
            ),
            (
                r#"{"schema_version":"1.1","seq":0,"kind":"state","job":{}}"#,
                EventError::MissingField("seq"),
            ),
            (
                r#"{"schema_version":"1.1","seq":"7","kind":"state","job":{}}"#,
                EventError::MissingField("seq"),
            ),
            (
                r#"{"schema_version":"1.1","seq":1,"kind":"state","job":{"state":"queued"}}"#,
                EventError::MissingField("job.id"),
            ),
        ] {
            assert_eq!(parse_event(bad), Err(err), "{bad}");
        }
    }

    #[test]
    fn seq_tracker_detects_gaps_and_stale_events() {
        let mut t = SeqTracker::default();
        assert_eq!(t.check(5), SeqCheck::InOrder);
        assert_eq!(t.check(6), SeqCheck::InOrder);
        assert_eq!(t.check(6), SeqCheck::Stale);
        assert_eq!(t.check(4), SeqCheck::Stale);
        assert_eq!(
            t.check(9),
            SeqCheck::Gap {
                expected: 7,
                got: 9
            }
        );
        assert_eq!(t.check(10), SeqCheck::InOrder);
    }
}
