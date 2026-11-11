# Import from phone (LAN upload gateway)

M10 lets a phone send clips (for example PS5 captures downloaded from the
PlayStation App) directly to the desktop over the local network, with no cloud
service and no mobile app. It follows spec 6.2 and 9.2.2.

Code:

- **Gateway:** `services/media-worker/openworld_moments/gateway/`, split into
  `__main__.py` (process), `app.py` (routes and page), and `uploads.py`
  (filename, type, and size rules).
- **Host:** `apps/desktop/src-tauri/src/phone.rs` (sessions, interfaces, QR
  code, import handoff) and the `phone_*` commands in `host.rs`.
- **UI:** `apps/desktop/src/PhoneImport.tsx` and `phone.ts`, at route
  `#/phone`.

## Network model

```text
Phone browser ──HTTP──▶ gateway (separate process, one private LAN address, random port)
                           │ writes only library/staging/phone/<session>/NNNN/<name>
                           ▼ JSON events on stdout
                        Rust host ──token──▶ worker (127.0.0.1): managed phone_upload import
```

- **The gateway is its own process.** It has no worker token, no database
  access, and no route to the library or the desktop API. The desktop API stays
  on loopback (M03).
- **It runs only while the Import from phone screen is open.** Before the
  screen starts a session, and after the session ends, nothing listens. Tests
  check both.
- **One address only:** it binds the single address the user picked from this
  computer's private IPv4 interfaces (10/8, 172.16/12, 192.168/16). Loopback,
  link-local, public, wildcard (`0.0.0.0`, `::`), and multicast addresses are
  refused by both the host and the gateway. Requests whose `Host` header is not
  that `address:port` are refused. The port is random unless one is given.
- **Plain HTTP with a secret link**, which the spec accepts for the MVP. The
  desktop screen states this limitation and warns against public or hotel
  Wi-Fi. Anyone on the same network who obtains the link can upload until the
  session ends.

## Token

- **Strength:** 32 random bytes from the OS, hex-encoded (256 bits). It is
  generated per session by the host (`Token::generate`) and given to the gateway
  on stdin, never in arguments or the environment.
- **In the URL:** `http://<address>:<port>/u/<token>/`, shown as text and a QR
  code.
- **The page protects it:** `Referrer-Policy: no-referrer`, `Cache-Control:
  no-store`, and a CSP that allows only its own nonce-tagged inline style and
  script plus `connect-src 'self'`.
- **Compared in constant time.** A wrong, expired, or finished token gets the
  same plain `404 This upload link is not active.` as any unknown path.
- **Lifetime:** at most 10 minutes. The session also ends when the desktop
  screen closes (the host closes the gateway's stdin), when the phone taps
  "I'm done", or when the app exits. A session cannot be reopened; a new one has
  a new token.

## Limits and checks

Each upload is one `PUT /u/<token>/files?name=<name>` with the file as the body.

| Check | Value | Where |
|---|---|---|
| Declared size required | `Content-Length`, else 411 | before writing |
| Per file | 10 GiB, else 413 | before writing |
| Per session | 100 files and 50 GiB, else 413 | before writing |
| Free space | 1 GiB must remain on the library volume, else 507 | before writing |
| Concurrent uploads | 2, else 429 | before writing |
| Extension | `.mp4`, `.m4v`, `.mov`, `.mkv`, `.webm`, else 415 | before writing |
| Content | First 12 bytes must be an MP4/MOV box (`ftyp`, `moov`, `mdat`, …) or the Matroska/WebM magic, matching the extension; else 415 and the file is deleted | while streaming |
| Size honesty | More bytes than declared → 400, deleted. Fewer, a disconnect, or 60 s without data → interrupted, deleted | while streaming |
| Expiry mid-upload | Rejected and deleted | while streaming |
| Media validity | The import probes the file (M04) and refuses damaged or non-video files (M05); refused files never reach managed storage | after upload |

### Filenames

The phone's filename is only a suggestion:

- **Reduced:** only its last path component survives.
- **Cleaned:**
  - control and reserved characters (`<>:"/\|?*`) become `_`;
  - leading and trailing dots and spaces are trimmed;
  - Windows device names (`CON`, `NUL`, `COM1`, …) are prefixed;
  - names are capped at 120 characters, keeping the extension.
- **Written exclusively** (`O_EXCL`) into a fresh numbered folder:
  `staging/phone/<session>/0001/<name>`. Duplicate names never collide, and a
  name can never leave the session folder.

The host re-checks the relative path it receives (`NNNN/<name>`) before using
it.

## Import handoff and staging cleanup

- **Each received file is imported straight away.** The host submits it as
  `POST /v1/imports` with `mode: managed`, `source_kind: phone_upload`, and
  idempotency key `phone-<session>-<seq>`. The library keeps its own
  content-addressed copy (M05), so the staged file is deleted as soon as that
  import finishes, whatever the outcome. Identical bytes resolve to the
  existing asset and show as "Already in the library".
- **Folder cleanup:** each per-file folder is removed with its imported copy.
  The session folder stays while the gateway runs, because the gateway checks
  free space in it and writes the next upload there; it is removed once the
  session has ended and it is empty. The gateway also recreates a missing
  staging folder, and reports a folder it cannot use as `storage_unavailable`,
  never as `disk_full`. When the app starts, `library/staging/phone/` is removed
  entirely (no session can be running then).
- **The desktop shows each file's state:** receiving (percent), added to the
  library (with a link), already in the library, not added (with the reason),
  refused (type, size, not a video), or interrupted.

## Gateway process protocol

`python -m openworld_moments.gateway --host <address> [--port N] --staging <dir>
[--expires-s 600] [--max-file-bytes …] [--max-files …] [--max-total-bytes …]`

- **stdin:** the token line, then held open. EOF ends the session.
- **stdout:** one JSON event per line:
  - `ready` (`host`, `port`, `expires_in_s`);
  - `upload_started`, `upload_progress`, `upload_done` (`seq`, `name`, `size`,
    `path`);
  - `upload_rejected` and `upload_refused` (`reason`), `upload_interrupted`;
  - `session_ended` (`reason`: `expired`, `finished_on_phone`,
    `closed_by_desktop`, `stopped`).
- **Startup errors:** one `error` line, exit code 2. Codes are
  `gateway.bad_address`, `gateway.missing_token`, `gateway.port_in_use`,
  `gateway.bind_failed`, and `gateway.bad_expiry`.
- **No logs** with file names or tokens.

## Tests

- **Gateway** (`services/media-worker/tests/gateway/test_gateway.py`, 39 tests):
  - filename traversal and sanitizing;
  - type and size rules;
  - wrong tokens, unknown paths, and the desktop API's routes return identical
    404s;
  - expired and finished sessions;
  - a foreign `Host` header;
  - page security headers;
  - uploads that land only in staging;
  - duplicates in separate folders;
  - unsupported and disguised files deleted;
  - oversized and over-limit uploads refused before writing;
  - the concurrency limit;
  - interrupted, short, oversized-body, and mid-stream-expiry uploads leaving
    nothing;
  - the real process: serving only while active; refusing wildcard, public,
    multicast, and link-local addresses and weak tokens; a chosen port and a busy
    port; the expiry bounds.
- **Host:** unit tests for private-address filtering and staged-path checks.
- **End-to-end** (`apps/desktop/src-tauri/tests/phone_e2e.rs`): with the real
  gateway and worker:
  - public and wildcard addresses refused;
  - a 256-bit token and a QR code;
  - one session at a time;
  - identical 404s;
  - a clip imported as a managed `phone_upload` asset, then the same clip as a
    duplicate;
  - a disguised file and a PDF refused and kept out of the library;
  - closing makes the port unreachable and leaves staging empty;
  - the phone's "I'm done" ends the session.

  Run:

  ```bash
  cargo test -p openworld-moments-desktop --test phone_e2e
  ```

- **UI** (`PhoneImport.test.tsx`):
  - the security warning before starting;
  - only private connections listed;
  - start on the chosen address, with the QR code, link, and countdown;
  - every upload state;
  - closing on request and when leaving the screen;
  - no private network;
  - start errors.

## Known limitations

- **No encryption:** traffic on the LAN is visible to others on the network.
  Use a trusted network only. A future native app can add authenticated
  encryption.
- **Network profile:** the desktop cannot tell a "public" Windows network from a
  private one. It lists private addresses and always shows the warning.
- **Windows firewall:** the first session may trigger a firewall prompt for the
  Python process. Allow it on private networks only.
- **No resumable uploads:** an interrupted upload must be sent again (out of
  scope for M10).
- **IPv4 only:** IPv6 LAN addresses are not offered.
