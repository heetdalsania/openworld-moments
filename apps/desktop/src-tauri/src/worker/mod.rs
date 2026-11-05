// SPDX-License-Identifier: AGPL-3.0-or-later
//! Python worker supervision (M03): spawn, readiness handshake, authenticated
//! requests, event stream, crash detection, restart, and shutdown.
//!
//! See docs/architecture/worker.md for the protocol and failure semantics.

mod protocol;
mod secret;
mod supervisor;
mod tail;

pub use protocol::{
    EventError, JobEvent, SeqCheck, SeqTracker, StartupLine, parse_event, parse_startup_line,
};
pub use secret::Token;
pub use supervisor::{
    Supervisor, SupervisorConfig, SupervisorError, WorkerCommand, WorkerInfo, WorkerStatus,
};
pub use tail::BoundedTail;
