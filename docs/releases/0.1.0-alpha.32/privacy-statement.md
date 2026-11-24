# Privacy statement — 0.1.0-alpha.32

OpenWorld Moments is a local desktop application. This statement describes the
Windows alpha exactly as shipped; it is checked against the
[threat model](../../security/threat-model.md) for this release.

## What the app never does

- No account, sign-in, telemetry, analytics, crash reporting or advertising.
- No upload of your footage, transcripts, projects or library to any server.
- No automatic update checks or catalog refreshes.
- No connection to a console, a game, game memory, network traffic or console services.

## What stays on your computer

Everything the app creates: the library database, playback copies, thumbnails,
waveforms, detected events, transcripts, projects, renders and settings. They live in
`%APPDATA%\org.openworldmoments.desktop` (library) and
`%LOCALAPPDATA%\org.openworldmoments.desktop` (WebView data). Original clips are never
modified; reference imports leave them where they are.

The desktop window and the bundled worker talk only over a loopback connection on this
computer, protected by a random per-launch token.

## The only network activity, and only when you choose it

| Feature | When | What leaves the app | To whom |
|---|---|---|---|
| Phone transfer | Only after you opt in during setup or in **Settings → Privacy choices**, and only while the **Import from phone** screen is open | Nothing leaves. A temporary page is served on the private network address you pick; your phone sends clips to the computer over plain HTTP, protected by a 256-bit secret link that expires after 10 minutes | Devices on your local network that have the link |
| Speech model download | Only after you opt in to downloads and choose **Install** for a model | A standard HTTPS file request (your IP address and Python's generic user agent; no identifiers) | `huggingface.co` and its download hosts (`*.huggingface.co`, `*.hf.co`), the only allowed origins and redirects; the file must match the signed catalog's size and SHA-256 |
| Diagnostics report | Only when you choose **Save report…** | Nothing is sent. A redacted report you previewed is saved where you choose; you decide whether to share it | Whoever you give the file to |

## Transcripts and review data

Optional transcription runs locally with a whisper.cpp program you install yourself.
Transcripts, detected text and privacy-review decisions can be deleted from the session
or project screens; deleting them never touches the original clips.

## Exports

Exports and render manifests contain no absolute paths unless you explicitly ask for
them. You are responsible for the rights to publish what you export, including music,
voice chat, other players and spoilers.

## Removing your data

Uninstalling keeps your library by default. To remove it, tick **Delete the application
data** during uninstall and confirm; external original clips are never deleted. See
[troubleshooting](../../guides/troubleshooting.md) and the
[known limitations](../../guides/known-limitations.md).

## Reporting

Report a privacy or security problem through [SECURITY.md](../../../SECURITY.md).
