// SPDX-License-Identifier: AGPL-3.0-or-later
//! Starts, watches, restarts, and stops the Python worker process.
//!
//! Lifecycle: `Stopped → Starting → Ready`. An unexpected exit moves to
//! `Restarting` and back to `Ready`, unless the worker crashed more than
//! `max_restarts` times within `restart_window`, which ends in `Failed`.
//! `stop()` closes the worker's stdin (its shutdown signal), waits up to
//! `shutdown_timeout`, then kills it.

use std::collections::VecDeque;
use std::net::IpAddr;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use futures_util::future::BoxFuture;
use futures_util::{FutureExt, StreamExt};
use serde::Serialize;
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::{Mutex, mpsc, oneshot, watch};
use tokio::time::{sleep, timeout};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::{HeaderValue, header::AUTHORIZATION};
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream};

use super::protocol::{
    EventError, JobEvent, SeqCheck, SeqTracker, StartupLine, parse_event, parse_startup_line,
};
use super::secret::Token;
use super::tail::BoundedTail;

pub const PROTOCOL_VERSION: u32 = 1;

/// How to launch the worker. `--library <dir>` is appended automatically.
#[derive(Debug, Clone)]
pub struct WorkerCommand {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: Option<PathBuf>,
}

#[derive(Debug, Clone)]
pub struct SupervisorConfig {
    pub command: WorkerCommand,
    pub library_dir: PathBuf,
    pub extra_args: Vec<String>,
    pub ready_timeout: Duration,
    pub shutdown_timeout: Duration,
    pub max_restarts: usize,
    pub restart_window: Duration,
    pub stderr_tail_bytes: usize,
}

impl SupervisorConfig {
    pub fn new(command: WorkerCommand, library_dir: PathBuf) -> Self {
        Self {
            command,
            library_dir,
            extra_args: Vec::new(),
            ready_timeout: Duration::from_secs(30),
            shutdown_timeout: Duration::from_secs(10),
            max_restarts: 3,
            restart_window: Duration::from_secs(60),
            stderr_tail_bytes: 8192,
        }
    }
}

/// Observable worker state, also sent to the UI.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum WorkerStatus {
    Stopped,
    Starting,
    Ready {
        port: u16,
        pid: u32,
        restarts: u32,
    },
    Restarting {
        attempt: u32,
        reason: String,
    },
    Failed {
        code: String,
        message: String,
        stderr_tail: String,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkerInfo {
    pub port: u16,
    pub pid: u32,
}

#[derive(Debug, Clone, PartialEq)]
pub enum SupervisorError {
    /// The program could not be started at all.
    Spawn(String),
    /// The worker started but reported, or ran into, a startup failure.
    Startup {
        code: String,
        message: String,
        stderr_tail: String,
    },
    NotRunning,
    /// The worker answered with an error (`body` is a contract ErrorInfo).
    Http {
        status: u16,
        body: Value,
    },
    Transport(String),
}

impl std::fmt::Display for SupervisorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Spawn(m) => write!(f, "could not start the worker: {m}"),
            Self::Startup { code, message, .. } => {
                write!(f, "worker failed to start ({code}): {message}")
            }
            Self::NotRunning => f.write_str("the worker is not running"),
            Self::Http { status, body } => write!(f, "worker returned {status}: {body}"),
            Self::Transport(m) => write!(f, "could not reach the worker: {m}"),
        }
    }
}

impl std::error::Error for SupervisorError {}

enum Control {
    Stop(oneshot::Sender<()>),
    Kill,
}

struct Running {
    port: u16,
    pid: u32,
    token: Token,
    control: mpsc::Sender<Control>,
}

struct Inner {
    config: SupervisorConfig,
    client: reqwest::Client,
    running: Mutex<Option<Running>>,
    status: watch::Sender<WorkerStatus>,
    stopping: AtomicBool,
    restarts_total: AtomicU32,
    recent_restarts: StdMutex<VecDeque<Instant>>,
}

/// Cheap to clone; all clones control the same worker.
#[derive(Clone)]
pub struct Supervisor {
    inner: Arc<Inner>,
}

impl Supervisor {
    pub fn new(config: SupervisorConfig) -> Self {
        let client = reqwest::Client::builder()
            .no_proxy() // loopback only; never route through a system proxy
            .timeout(Duration::from_secs(30))
            .build()
            .expect("HTTP client builds with static settings");
        let (status, _) = watch::channel(WorkerStatus::Stopped);
        Self {
            inner: Arc::new(Inner {
                config,
                client,
                running: Mutex::new(None),
                status,
                stopping: AtomicBool::new(false),
                restarts_total: AtomicU32::new(0),
                recent_restarts: StdMutex::new(VecDeque::new()),
            }),
        }
    }

    pub fn status(&self) -> WorkerStatus {
        self.inner.status.borrow().clone()
    }

    pub fn subscribe_status(&self) -> watch::Receiver<WorkerStatus> {
        self.inner.status.subscribe()
    }

    /// Start the worker and wait for its readiness handshake.
    pub async fn start(&self) -> Result<WorkerInfo, SupervisorError> {
        if let Some(running) = self.inner.running.lock().await.as_ref() {
            return Ok(WorkerInfo {
                port: running.port,
                pid: running.pid,
            });
        }
        self.inner.stopping.store(false, Ordering::SeqCst);
        launch(self.inner.clone()).await
    }

    /// Graceful shutdown: close stdin, wait, then kill if needed.
    pub async fn stop(&self) {
        self.inner.stopping.store(true, Ordering::SeqCst);
        let running = self.inner.running.lock().await.take();
        if let Some(running) = running {
            let (done_tx, done_rx) = oneshot::channel();
            if running.control.send(Control::Stop(done_tx)).await.is_ok() {
                let _ = timeout(
                    self.inner.config.shutdown_timeout + Duration::from_secs(5),
                    done_rx,
                )
                .await;
            }
        }
        self.inner.status.send_replace(WorkerStatus::Stopped);
    }

    /// Kill the worker as a crash would (for tests and diagnostics). The
    /// supervisor treats it as unexpected and applies the restart policy.
    #[doc(hidden)]
    pub async fn simulate_crash(&self) {
        if let Some(running) = self.inner.running.lock().await.as_ref() {
            let _ = running.control.send(Control::Kill).await;
        }
    }

    async fn endpoint(&self) -> Result<(u16, Token), SupervisorError> {
        let guard = self.inner.running.lock().await;
        let running = guard.as_ref().ok_or(SupervisorError::NotRunning)?;
        Ok((running.port, running.token.clone()))
    }

    /// Authenticated request to the worker API. Errors carry the worker's ErrorInfo.
    pub async fn request(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<&Value>,
        correlation_id: Option<&str>,
    ) -> Result<Value, SupervisorError> {
        let (port, token) = self.endpoint().await?;
        let mut builder = self
            .inner
            .client
            .request(method, format!("http://127.0.0.1:{port}{path}"))
            .bearer_auth(token.expose());
        if let Some(body) = body {
            builder = builder.json(body);
        }
        if let Some(id) = correlation_id {
            builder = builder.header("x-correlation-id", id);
        }
        let response = builder
            .send()
            .await
            .map_err(|e| SupervisorError::Transport(e.without_url().to_string()))?;
        let status = response.status();
        let body: Value = response.json().await.unwrap_or(Value::Null);
        if status.is_success() {
            Ok(body)
        } else {
            Err(SupervisorError::Http {
                status: status.as_u16(),
                body,
            })
        }
    }

    pub async fn health(&self) -> Result<Value, SupervisorError> {
        self.request(reqwest::Method::GET, "/v1/health", None, None)
            .await
    }

    pub async fn submit_job(
        &self,
        kind: &str,
        params: Value,
        correlation_id: Option<&str>,
    ) -> Result<Value, SupervisorError> {
        let body = json!({ "kind": kind, "params": params });
        self.request(
            reqwest::Method::POST,
            "/v1/jobs",
            Some(&body),
            correlation_id,
        )
        .await
    }

    pub async fn get_job(&self, job_id: &str) -> Result<Value, SupervisorError> {
        self.request(
            reqwest::Method::GET,
            &format!("/v1/jobs/{job_id}"),
            None,
            None,
        )
        .await
    }

    pub async fn cancel_job(&self, job_id: &str) -> Result<Value, SupervisorError> {
        self.request(
            reqwest::Method::POST,
            &format!("/v1/jobs/{job_id}/cancel"),
            None,
            None,
        )
        .await
    }

    pub async fn list_jobs(&self) -> Result<Value, SupervisorError> {
        self.request(reqwest::Method::GET, "/v1/jobs", None, None)
            .await
    }

    /// Open the job event stream for the current worker process.
    pub async fn connect_events(&self) -> Result<EventStream, SupervisorError> {
        let (port, token) = self.endpoint().await?;
        let mut request = format!("ws://127.0.0.1:{port}/v1/jobs/events")
            .into_client_request()
            .map_err(|e| SupervisorError::Transport(e.to_string()))?;
        let auth = HeaderValue::from_str(&format!("Bearer {}", token.expose()))
            .map_err(|e| SupervisorError::Transport(e.to_string()))?;
        request.headers_mut().insert(AUTHORIZATION, auth);
        let (ws, _) = tokio_tungstenite::connect_async(request)
            .await
            .map_err(|e| SupervisorError::Transport(e.to_string()))?;
        Ok(EventStream {
            ws,
            seq: SeqTracker::default(),
            malformed: 0,
        })
    }
}

/// Ordered job events from one worker process.
pub struct EventStream {
    ws: WebSocketStream<MaybeTlsStream<TcpStream>>,
    seq: SeqTracker,
    /// Frames that could not be parsed and were skipped.
    pub malformed: u64,
}

impl EventStream {
    /// Next event with its ordering check. `None` when the stream ends (worker
    /// stopped or restarted: reconnect and resynchronize with GET /v1/jobs).
    /// Malformed frames are counted and returned as errors without closing.
    pub async fn next(&mut self) -> Option<Result<(JobEvent, SeqCheck), EventError>> {
        loop {
            match self.ws.next().await {
                Some(Ok(Message::Text(text))) => {
                    return Some(match parse_event(text.as_str()) {
                        Ok(event) => {
                            let check = self.seq.check(event.seq);
                            Ok((event, check))
                        }
                        Err(err) => {
                            self.malformed += 1;
                            Err(err)
                        }
                    });
                }
                Some(Ok(Message::Close(_))) | Some(Err(_)) | None => return None,
                Some(Ok(_)) => continue,
            }
        }
    }
}

fn startup_error(
    code: &str,
    message: impl Into<String>,
    tail: &StdMutex<BoundedTail>,
) -> SupervisorError {
    SupervisorError::Startup {
        code: code.to_string(),
        message: message.into(),
        stderr_tail: tail.lock().map(|t| t.text()).unwrap_or_default(),
    }
}

fn launch(inner: Arc<Inner>) -> BoxFuture<'static, Result<WorkerInfo, SupervisorError>> {
    async move {
        inner.status.send_replace(WorkerStatus::Starting);
        let result = spawn_and_handshake(&inner).await;
        match result {
            Ok((info, token, child, stdin, tail, stderr_reader)) => {
                let (control_tx, control_rx) = mpsc::channel(4);
                *inner.running.lock().await = Some(Running {
                    port: info.port,
                    pid: info.pid,
                    token,
                    control: control_tx,
                });
                inner.status.send_replace(WorkerStatus::Ready {
                    port: info.port,
                    pid: info.pid,
                    restarts: inner.restarts_total.load(Ordering::SeqCst),
                });
                tokio::spawn(monitor(
                    inner.clone(),
                    child,
                    stdin,
                    control_rx,
                    tail,
                    stderr_reader,
                ));
                Ok(info)
            }
            Err(err) => {
                if let SupervisorError::Startup {
                    code,
                    message,
                    stderr_tail,
                } = &err
                {
                    inner.status.send_replace(WorkerStatus::Failed {
                        code: code.clone(),
                        message: message.clone(),
                        stderr_tail: stderr_tail.clone(),
                    });
                } else {
                    inner.status.send_replace(WorkerStatus::Failed {
                        code: "worker.spawn_failed".into(),
                        message: err.to_string(),
                        stderr_tail: String::new(),
                    });
                }
                Err(err)
            }
        }
    }
    .boxed()
}

type Spawned = (
    WorkerInfo,
    Token,
    Child,
    ChildStdin,
    Arc<StdMutex<BoundedTail>>,
    Option<tokio::task::JoinHandle<()>>,
);

async fn spawn_and_handshake(inner: &Inner) -> Result<Spawned, SupervisorError> {
    let config = &inner.config;
    let token = Token::generate()
        .map_err(|e| SupervisorError::Spawn(format!("no randomness for token: {e}")))?;
    let mut command = Command::new(&config.command.program);
    command
        .args(&config.command.args)
        .arg("--library")
        .arg(&config.library_dir)
        .args(&config.extra_args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if let Some(cwd) = &config.command.cwd {
        command.current_dir(cwd);
    }
    crate::platform::hide_console(&mut command);
    let mut child = command
        .spawn()
        .map_err(|e| SupervisorError::Spawn(e.to_string()))?;

    let tail = Arc::new(StdMutex::new(BoundedTail::new(
        config.stderr_tail_bytes,
        vec![token.expose().to_string()],
    )));
    let stderr_reader = child.stderr.take().map(|stderr| {
        let tail = tail.clone();
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                if let Ok(mut t) = tail.lock() {
                    t.push_line(&line);
                }
            }
        })
    });

    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| SupervisorError::Spawn("no stdin pipe".into()))?;
    let token_line = format!("{}\n", token.expose());
    if stdin.write_all(token_line.as_bytes()).await.is_err() || stdin.flush().await.is_err() {
        let _ = child.kill().await;
        return Err(startup_error(
            "worker.exited",
            "the worker exited before reading its token",
            &tail,
        ));
    }

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| SupervisorError::Spawn("no stdout pipe".into()))?;
    let mut lines = BufReader::new(stdout).lines();
    let first = match timeout(config.ready_timeout, lines.next_line()).await {
        Ok(Ok(Some(line))) => line,
        Ok(_) => {
            let status = child
                .wait()
                .await
                .map(|s| s.to_string())
                .unwrap_or_default();
            sleep(Duration::from_millis(50)).await; // let the stderr reader catch up
            return Err(startup_error(
                "worker.exited",
                format!("the worker exited during startup ({status})"),
                &tail,
            ));
        }
        Err(_) => {
            let _ = child.kill().await;
            return Err(startup_error(
                "worker.ready_timeout",
                "the worker did not become ready in time",
                &tail,
            ));
        }
    };
    // Anything after the handshake on stdout is ignored; keep draining it.
    tokio::spawn(async move { while let Ok(Some(_)) = lines.next_line().await {} });

    match parse_startup_line(&first) {
        Ok(StartupLine::Ready {
            protocol,
            host,
            port,
            pid,
            ..
        }) => {
            let loopback = host
                .parse::<IpAddr>()
                .map(|ip| ip.is_loopback())
                .unwrap_or(false);
            if protocol != PROTOCOL_VERSION || !loopback {
                let _ = child.kill().await;
                return Err(startup_error(
                    "worker.protocol_mismatch",
                    format!("unexpected handshake (protocol {protocol}, host {host})"),
                    &tail,
                ));
            }
            Ok((
                WorkerInfo { port, pid },
                token,
                child,
                stdin,
                tail,
                stderr_reader,
            ))
        }
        Ok(StartupLine::Error { code, message }) => {
            let _ = timeout(Duration::from_secs(5), child.wait()).await;
            Err(startup_error(&code, message, &tail))
        }
        Err(problem) => {
            let _ = child.kill().await;
            Err(startup_error("worker.protocol_mismatch", problem, &tail))
        }
    }
}

async fn monitor(
    inner: Arc<Inner>,
    mut child: Child,
    stdin: ChildStdin,
    mut control: mpsc::Receiver<Control>,
    tail: Arc<StdMutex<BoundedTail>>,
    stderr_reader: Option<tokio::task::JoinHandle<()>>,
) {
    let mut stdin = Some(stdin);
    let exit = loop {
        tokio::select! {
            status = child.wait() => break status,
            message = control.recv() => match message {
                Some(Control::Stop(done)) => {
                    drop(stdin.take()); // EOF on stdin asks the worker to shut down
                    if timeout(inner.config.shutdown_timeout, child.wait()).await.is_err() {
                        let _ = child.kill().await;
                    }
                    let _ = done.send(());
                    return;
                }
                Some(Control::Kill) => { let _ = child.start_kill(); }
                None => { let _ = child.start_kill(); }
            },
        }
    };

    // The process can exit before the pipe reader has consumed its last records.
    // Drain before publishing a crash-loop snapshot; an inherited open pipe must
    // not prevent shutdown/restart indefinitely.
    if let Some(mut reader) = stderr_reader
        && timeout(Duration::from_secs(1), &mut reader).await.is_err()
    {
        reader.abort();
    }
    *inner.running.lock().await = None;
    if inner.stopping.load(Ordering::SeqCst) {
        inner.status.send_replace(WorkerStatus::Stopped);
        return;
    }
    let reason = match exit {
        Ok(status) => format!("worker exited unexpectedly ({status})"),
        Err(e) => format!("lost track of the worker process: {e}"),
    };

    let attempt = {
        let mut recent = inner.recent_restarts.lock().expect("restart log lock");
        let now = Instant::now();
        while recent
            .front()
            .is_some_and(|t| now.duration_since(*t) > inner.config.restart_window)
        {
            recent.pop_front();
        }
        if recent.len() >= inner.config.max_restarts {
            None
        } else {
            recent.push_back(now);
            Some(recent.len() as u32)
        }
    };
    let Some(attempt) = attempt else {
        inner.status.send_replace(WorkerStatus::Failed {
            code: "worker.crash_loop".into(),
            message: format!(
                "{reason}; restarted {} times within {:?}",
                inner.config.max_restarts, inner.config.restart_window
            ),
            stderr_tail: tail.lock().map(|t| t.text()).unwrap_or_default(),
        });
        return;
    };

    inner
        .status
        .send_replace(WorkerStatus::Restarting { attempt, reason });
    sleep(Duration::from_millis(250 * 2u64.pow(attempt - 1))).await;
    if inner.stopping.load(Ordering::SeqCst) {
        inner.status.send_replace(WorkerStatus::Stopped);
        return;
    }
    inner.restarts_total.fetch_add(1, Ordering::SeqCst);
    let _ = launch(inner).await; // a failed restart leaves status = Failed
}
