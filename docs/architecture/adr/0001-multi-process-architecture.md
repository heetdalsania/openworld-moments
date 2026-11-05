# ADR-0001: Multi-process desktop architecture

- Status: Accepted
- Date: 2026-11-04
- Milestone: M00
- Deciders: project maintainers

## Context

OpenWorld Moments needs a native desktop experience (file dialogs, watched
folders, tray, keychain) and a mature media/ML ecosystem (FFmpeg, OpenCV, ONNX
Runtime, NumPy/SciPy). It must stay local-first, treat every media file as
untrusted, and keep the analysis engine replaceable. See specification §9.1–9.3
and §22.

## Decision

The application runs as separate processes with versioned contracts between
them:

1. **React + TypeScript UI** (Vite) rendered by **Tauri 2**.
2. **Rust Tauri host** owning application lifecycle, OS integration, watched
   folders, secure per-launch tokens, and worker supervision.
3. **Python 3.12 media worker** owning probing, analysis, persistence (SQLite +
   FTS5), and FFmpeg orchestration. It exposes a token-authenticated HTTP API
   bound only to `127.0.0.1` on an ephemeral port (added in M03).
4. **FFmpeg/FFprobe** and optional model runtimes run as child processes with
   argument arrays, never shell strings.
5. A **temporary LAN upload gateway** for phone imports is separate from the
   desktop API (added in M10).

Contracts are JSON Schemas in `packages/contracts/` (M01) from which TypeScript
and Python types are generated. Layout follows specification §9.3.

## Consequences

- Python crashes or memory spikes during analysis do not take down the UI; the
  host can restart the worker.
- Three toolchains (Node/pnpm, Rust/Cargo, Python/uv) must be pinned, linted,
  and tested in CI. Contributors need all three to run the full app.
- Packaging must ship a Python runtime and FFmpeg build alongside the Tauri
  binary (M29), with license and SBOM tracking (M30).
- The worker can later be embedded or rewritten without changing the UI,
  provided the contracts are honoured.
- Local IPC adds an authentication surface, mitigated by loopback binding and a
  per-launch bearer token.

## Alternatives considered

- **Electron + Node media code**: larger runtime and a weaker ML ecosystem.
- **All-Rust application**: strong packaging, but ML/CV iteration would be much
  slower and detector contributors would face a higher barrier.
- **Python-only desktop (Qt)**: one language, but a weaker web-based UI story
  and harder separation between UI and untrusted media processing.
- **Cloud processing**: violates the local-first and privacy goals.
