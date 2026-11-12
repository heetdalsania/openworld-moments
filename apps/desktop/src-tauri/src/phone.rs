// SPDX-License-Identifier: AGPL-3.0-or-later
//! "Import from phone" sessions (M10, spec 9.2.2).
//!
//! While the desktop screen is open, the host runs the upload gateway
//! (`python -m openworld_moments.gateway`) as its own process, bound to one private
//! LAN address the user picked. The gateway shares nothing with the desktop API:
//! it gets a fresh 256-bit token on stdin, writes uploads only to this session's
//! staging folder, and reports events as JSON lines. The host turns each received
//! file into a managed `phone_upload` import through the worker (so M04/M05
//! validation decides what enters the library) and removes the staged copy once
//! that import finishes. Closing the screen, the phone's "I'm done", or the
//! ten-minute expiry ends the session and the gateway exits.

use std::net::{IpAddr, Ipv4Addr};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::watch;

use crate::worker::{Supervisor, Token, WorkerCommand};

/// Gateway session length (spec 9.2.2: ten minutes).
pub const SESSION_SECONDS: u64 = 600;
const READY_TIMEOUT: Duration = Duration::from_secs(20);

/// A network interface the gateway may listen on.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct NetInterface {
    pub name: String,
    pub address: String,
}

/// Private IPv4 unicast addresses (10/8, 172.16/12, 192.168/16): the only places a
/// session may listen. Loopback, link-local, and public addresses are never offered.
pub fn is_private_lan(ip: Ipv4Addr) -> bool {
    ip.is_private() && !ip.is_loopback() && !ip.is_link_local()
}

pub fn private_interfaces() -> Vec<NetInterface> {
    let mut found: Vec<NetInterface> = if_addrs::get_if_addrs()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|iface| match iface.addr {
            if_addrs::IfAddr::V4(v4) if is_private_lan(v4.ip) => Some(NetInterface {
                name: iface.name,
                address: v4.ip.to_string(),
            }),
            _ => None,
        })
        .collect();
    found.sort_by(|a, b| a.name.cmp(&b.name).then(a.address.cmp(&b.address)));
    found.dedup();
    found
}

/// One file the phone sent, as the desktop shows it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PhoneUpload {
    pub seq: u64,
    pub name: String,
    pub size: u64,
    pub received: u64,
    /// `receiving`, `importing`, `imported`, `duplicate`, `import_failed`,
    /// `rejected`, or `interrupted`.
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub asset_id: Option<String>,
}

/// What the "Import from phone" screen shows.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Default)]
pub struct PhoneStatus {
    /// `idle`, `starting`, `active`, or `ended`.
    pub state: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub address: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub port: Option<u16>,
    /// The upload page (contains the token); only while active.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    /// QR code of `url` as SVG; only while active.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub qr_svg: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_in_s: Option<u64>,
    pub uploads: Vec<PhoneUpload>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ended_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<Value>,
}

#[derive(Debug, Clone)]
pub struct PhoneConfig {
    /// The Python interpreter and working directory of the worker.
    pub command: WorkerCommand,
    /// `library/staging/phone`; each session gets a subfolder.
    pub staging_root: PathBuf,
    pub session_seconds: u64,
    /// Tests only: allow binding 127.0.0.1.
    pub allow_loopback: bool,
}

struct Running {
    child: Child,
    stdin: Option<ChildStdin>,
    staging: PathBuf,
    session: String,
}

struct State {
    status: PhoneStatus,
    running: Option<Running>,
    started_at: Option<tokio::time::Instant>,
}

/// One "Import from phone" session at a time. Cheap to clone.
#[derive(Clone)]
pub struct PhoneGateway {
    config: PhoneConfig,
    state: Arc<Mutex<State>>,
    changes: watch::Sender<PhoneStatus>,
}

fn phone_error(code: &str, message: &str) -> Value {
    json!({ "code": code, "message": message, "retryable": false })
}

impl PhoneGateway {
    pub fn new(config: PhoneConfig) -> Self {
        let idle = PhoneStatus {
            state: "idle".into(),
            ..PhoneStatus::default()
        };
        let (changes, _) = watch::channel(idle.clone());
        Self {
            config,
            state: Arc::new(Mutex::new(State {
                status: idle,
                running: None,
                started_at: None,
            })),
            changes,
        }
    }

    pub fn subscribe(&self) -> watch::Receiver<PhoneStatus> {
        self.changes.subscribe()
    }

    pub fn status(&self) -> PhoneStatus {
        let state = self.state.lock().expect("phone state");
        let mut status = state.status.clone();
        if let (Some(started), "active") = (state.started_at, status.state.as_str()) {
            let elapsed = started.elapsed().as_secs();
            status.expires_in_s = Some(self.config.session_seconds.saturating_sub(elapsed));
        }
        status
    }

    fn update(&self, change: impl FnOnce(&mut PhoneStatus)) {
        let snapshot = {
            let mut state = self.state.lock().expect("phone state");
            change(&mut state.status);
            state.status.clone()
        };
        self.changes.send_replace(snapshot);
    }

    fn allowed(&self, address: &str) -> bool {
        match address.parse::<IpAddr>() {
            Ok(IpAddr::V4(ip)) if ip.is_loopback() => self.config.allow_loopback,
            Ok(IpAddr::V4(_)) => private_interfaces().iter().any(|i| i.address == address),
            _ => false,
        }
    }

    /// Start a session on `address` (one of [`private_interfaces`]); `port` 0 picks one.
    pub async fn start(
        &self,
        supervisor: Option<Supervisor>,
        address: &str,
        port: u16,
    ) -> Result<PhoneStatus, Value> {
        if self.state.lock().expect("phone state").running.is_some() {
            return Err(phone_error(
                "phone.already_active",
                "A phone import session is already open.",
            ));
        }
        if !self.allowed(address) {
            return Err(phone_error(
                "phone.address_not_allowed",
                "Choose one of this computer's private network addresses.",
            ));
        }
        let token = Token::generate()
            .map_err(|_| phone_error("phone.no_randomness", "Could not create a session token."))?;
        let session = Token::generate()
            .map(|t| t.expose()[..16].to_string())
            .map_err(|_| phone_error("phone.no_randomness", "Could not create a session."))?;
        let staging = self.config.staging_root.join(&session);
        self.update(|s| {
            *s = PhoneStatus {
                state: "starting".into(),
                address: Some(address.to_string()),
                ..PhoneStatus::default()
            }
        });

        let command = &self.config.command;
        let mut process = Command::new(&command.program);
        process
            .args(["-m", "openworld_moments.gateway", "--host", address])
            .arg("--port")
            .arg(port.to_string())
            .arg("--staging")
            .arg(&staging)
            .arg("--expires-s")
            .arg(self.config.session_seconds.to_string())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        if let Some(cwd) = &command.cwd {
            process.current_dir(cwd);
        }
        crate::platform::hide_console(&mut process);
        let mut child = match process.spawn() {
            Ok(child) => child,
            Err(_) => {
                return Err(self.fail("phone.spawn_failed", "The upload gateway could not start."));
            }
        };
        let mut stdin = child.stdin.take();
        if let Some(pipe) = stdin.as_mut() {
            let line = format!("{}\n", token.expose());
            if pipe.write_all(line.as_bytes()).await.is_err() || pipe.flush().await.is_err() {
                return Err(self.fail(
                    "phone.spawn_failed",
                    "The upload gateway did not accept its token.",
                ));
            }
        }
        let Some(stdout) = child.stdout.take() else {
            return Err(self.fail("phone.spawn_failed", "The upload gateway has no output."));
        };
        let mut lines = BufReader::new(stdout).lines();
        let ready = tokio::time::timeout(READY_TIMEOUT, lines.next_line()).await;
        let event: Value = match ready {
            Ok(Ok(Some(line))) => serde_json::from_str(&line).unwrap_or(Value::Null),
            _ => Value::Null,
        };
        if event["event"] != "ready" {
            let _ = child.kill().await;
            let code = event["code"].as_str().unwrap_or("phone.not_ready");
            let message = event["message"]
                .as_str()
                .unwrap_or("The upload gateway did not start.");
            return Err(self.fail(code, message));
        }
        let bound = event["port"].as_u64().unwrap_or(0) as u16;
        let url = format!("http://{address}:{bound}/u/{}/", token.expose());
        let qr = qrcode::QrCode::new(url.as_bytes())
            .map(|code| {
                code.render::<qrcode::render::svg::Color>()
                    .min_dimensions(240, 240)
                    .quiet_zone(true)
                    .build()
            })
            .ok();
        {
            let mut state = self.state.lock().expect("phone state");
            state.running = Some(Running {
                child,
                stdin,
                staging: staging.clone(),
                session,
            });
            state.started_at = Some(tokio::time::Instant::now());
        }
        self.update(|s| {
            s.state = "active".into();
            s.port = Some(bound);
            s.url = Some(url);
            s.qr_svg = qr;
            s.expires_in_s = Some(self.config.session_seconds);
        });
        let gateway = self.clone();
        tokio::spawn(async move {
            while let Ok(Some(line)) = lines.next_line().await {
                if let Ok(event) = serde_json::from_str::<Value>(&line) {
                    gateway.on_event(&event, supervisor.as_ref(), &staging);
                }
            }
            gateway.on_exit().await;
        });
        Ok(self.status())
    }

    fn fail(&self, code: &str, message: &str) -> Value {
        let error = phone_error(code, message);
        self.update(|s| {
            s.state = "ended".into();
            s.url = None;
            s.qr_svg = None;
            s.error = Some(error.clone());
        });
        error
    }

    fn on_event(&self, event: &Value, supervisor: Option<&Supervisor>, staging: &Path) {
        let seq = event["seq"].as_u64().unwrap_or(0);
        match event["event"].as_str() {
            Some("upload_started") => self.update(|s| {
                s.uploads.push(PhoneUpload {
                    seq,
                    name: event["name"].as_str().unwrap_or("video").to_string(),
                    size: event["size"].as_u64().unwrap_or(0),
                    received: 0,
                    status: "receiving".into(),
                    reason: None,
                    asset_id: None,
                })
            }),
            Some("upload_progress") => self.update(|s| {
                if let Some(u) = s.uploads.iter_mut().find(|u| u.seq == seq) {
                    u.received = event["received"].as_u64().unwrap_or(u.received);
                }
            }),
            Some("upload_rejected") | Some("upload_interrupted") => {
                let status = if event["event"] == "upload_rejected" {
                    "rejected"
                } else {
                    "interrupted"
                };
                self.update(|s| {
                    if let Some(u) = s.uploads.iter_mut().find(|u| u.seq == seq) {
                        u.status = status.into();
                        u.reason = event["reason"].as_str().map(str::to_string);
                    }
                });
            }
            Some("upload_done") => {
                let relative = event["path"].as_str().unwrap_or_default();
                self.update(|s| {
                    if let Some(u) = s.uploads.iter_mut().find(|u| u.seq == seq) {
                        u.received = u.size;
                        u.status = "importing".into();
                    }
                });
                if let Some(path) = staged_path(staging, relative) {
                    self.import(supervisor.cloned(), seq, path);
                }
            }
            Some("session_ended") => {
                let reason = event["reason"].as_str().unwrap_or("ended").to_string();
                self.update(|s| s.ended_reason = Some(reason));
            }
            _ => {}
        }
    }

    /// Hand one staged file to the worker as a managed `phone_upload` import, follow
    /// the job, then delete the staged copy (the library keeps its own copy).
    fn import(&self, supervisor: Option<Supervisor>, seq: u64, path: PathBuf) {
        let gateway = self.clone();
        let session = self
            .state
            .lock()
            .expect("phone state")
            .running
            .as_ref()
            .map(|r| r.session.clone())
            .unwrap_or_default();
        tokio::spawn(async move {
            let outcome = match supervisor {
                Some(supervisor) => run_import(&supervisor, &session, seq, &path).await,
                None => Err("worker.unavailable".to_string()),
            };
            // The gateway keeps writing to this session's staging folder while it
            // runs, so only an ended session's folder may go once it is empty.
            let ended = path.parent().and_then(Path::parent).is_none_or(|folder| {
                gateway
                    .state
                    .lock()
                    .expect("phone state")
                    .running
                    .as_ref()
                    .is_none_or(|r| r.staging != folder)
            });
            remove_staged(&path, ended);
            gateway.update(|s| {
                if let Some(u) = s.uploads.iter_mut().find(|u| u.seq == seq) {
                    match outcome {
                        Ok((status, asset)) => {
                            u.status = status;
                            u.asset_id = asset;
                        }
                        Err(code) => {
                            u.status = "import_failed".into();
                            u.reason = Some(code);
                        }
                    }
                }
            });
        });
    }

    /// End the session now (screen closed). Waits briefly for a clean exit.
    pub async fn stop(&self) {
        let running = self.state.lock().expect("phone state").running.take();
        if let Some(mut running) = running {
            drop(running.stdin.take()); // EOF: the gateway ends the session and exits
            if tokio::time::timeout(Duration::from_secs(3), running.child.wait())
                .await
                .is_err()
            {
                let _ = running.child.kill().await;
            }
            self.finish("closed_by_desktop", &running.staging);
        }
    }

    async fn on_exit(&self) {
        let running = self.state.lock().expect("phone state").running.take();
        if let Some(mut running) = running {
            let _ = tokio::time::timeout(Duration::from_secs(3), running.child.wait()).await;
            let _ = running.child.kill().await;
            self.finish("ended", &running.staging);
        }
    }

    fn finish(&self, fallback: &str, staging: &Path) {
        self.update(|s| {
            s.state = "ended".into();
            s.url = None;
            s.qr_svg = None;
            s.expires_in_s = None;
            if s.ended_reason.is_none() {
                s.ended_reason = Some(fallback.into());
            }
            for u in s.uploads.iter_mut().filter(|u| u.status == "receiving") {
                u.status = "interrupted".into();
            }
        });
        // Imports still running delete their own files; empty folders go now.
        let _ = std::fs::remove_dir(staging);
        self.state.lock().expect("phone state").started_at = None;
    }
}

/// `staging/<seq>/<name>` from the gateway's relative path, refusing anything else.
fn staged_path(staging: &Path, relative: &str) -> Option<PathBuf> {
    let mut parts = relative.split('/');
    let (Some(seq), Some(name), None) = (parts.next(), parts.next(), parts.next()) else {
        return None;
    };
    let seq_ok = seq.len() == 4 && seq.bytes().all(|b| b.is_ascii_digit());
    let name_ok =
        !name.is_empty() && name != "." && name != ".." && !name.contains(['\\', ':', '\0']);
    (seq_ok && name_ok).then(|| staging.join(seq).join(name))
}

/// Delete a staged copy and its `<seq>` folder. The session folder goes too (once
/// empty) only when `session_ended`: a live gateway still checks free space in it
/// and writes the next upload there.
fn remove_staged(path: &Path, session_ended: bool) {
    let _ = std::fs::remove_file(path);
    if let Some(folder) = path.parent() {
        let _ = std::fs::remove_dir(folder);
        if let Some(session) = folder.parent().filter(|_| session_ended) {
            let _ = std::fs::remove_dir(session); // only once empty
        }
    }
}

async fn run_import(
    supervisor: &Supervisor,
    session: &str,
    seq: u64,
    path: &Path,
) -> Result<(String, Option<String>), String> {
    let body = json!({
        "paths": [path],
        "mode": "managed",
        "recursive": false,
        "source_kind": "phone_upload",
        "idempotency_key": format!("phone-{session}-{seq}"),
    });
    let job = supervisor
        .request(reqwest::Method::POST, "/v1/imports", Some(&body), None)
        .await
        .map_err(|_| "import.not_started".to_string())?;
    let id = job["id"].as_str().unwrap_or_default().to_string();
    let finished = loop {
        let job = supervisor
            .get_job(&id)
            .await
            .map_err(|_| "worker.unavailable".to_string())?;
        if matches!(
            job["state"].as_str(),
            Some("ready" | "failed" | "cancelled")
        ) {
            break job;
        }
        tokio::time::sleep(Duration::from_millis(300)).await;
    };
    let item = &finished["result"]["items"][0];
    let asset = item["asset_id"].as_str().map(str::to_string);
    match item["outcome"].as_str() {
        Some("imported") => Ok(("imported".into(), asset)),
        Some("existing" | "relinked") => Ok(("duplicate".into(), asset)),
        _ => Err(item["error"]["code"]
            .as_str()
            .or_else(|| finished["error"]["code"].as_str())
            .unwrap_or("import.failed")
            .to_string()),
    }
}

/// Remove leftovers of a session that never finished (app start: none is running).
pub fn clean_staging(root: &Path) {
    let _ = std::fs::remove_dir_all(root);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_private_lan_addresses_qualify() {
        for ok in ["192.168.1.20", "10.0.0.5", "172.16.4.1", "172.31.255.254"] {
            assert!(is_private_lan(ok.parse().unwrap()), "{ok}");
        }
        for bad in [
            "127.0.0.1",
            "169.254.3.3",
            "8.8.8.8",
            "172.32.0.1",
            "0.0.0.0",
            "100.64.0.1",
        ] {
            assert!(!is_private_lan(bad.parse().unwrap()), "{bad}");
        }
        for iface in private_interfaces() {
            assert!(is_private_lan(iface.address.parse().unwrap()));
        }
    }

    #[test]
    fn imports_keep_a_live_session_folder() {
        let dir = std::env::temp_dir().join(format!("owm-phone-{}", std::process::id()));
        let session = dir.join("session");
        let first = session.join("0001").join("clip.mp4");
        std::fs::create_dir_all(first.parent().unwrap()).unwrap();
        std::fs::write(&first, b"video").unwrap();
        remove_staged(&first, false);
        assert!(!first.parent().unwrap().exists());
        assert!(
            session.is_dir(),
            "a live gateway still needs its staging folder"
        );

        let second = session.join("0002").join("clip.mp4");
        std::fs::create_dir_all(second.parent().unwrap()).unwrap();
        std::fs::write(&second, b"video").unwrap();
        remove_staged(&second, true);
        assert!(!session.exists(), "an ended session leaves no empty folder");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn staged_paths_stay_in_their_session() {
        let root = Path::new("/lib/staging/phone/abc");
        assert_eq!(
            staged_path(root, "0001/clip.mp4"),
            Some(root.join("0001").join("clip.mp4"))
        );
        for bad in [
            "../0001/clip.mp4",
            "0001/../../x",
            "0001/..",
            "1/clip.mp4",
            "0001/sub/clip.mp4",
            "0001/C:\\x.mp4",
            "0001/",
            "",
        ] {
            assert_eq!(staged_path(root, bad), None, "{bad}");
        }
    }
}
