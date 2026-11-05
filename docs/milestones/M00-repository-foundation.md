# M00 — Repository foundation

## Objective

Create the buildable, licensed, and continuously validated monorepo that every later milestone will extend. This milestone must establish conventions without implementing product behavior.

## Dependencies

None.

## Required context

Read specification sections 9, 13, 15, 16 Phase 0, and 22.

## In scope

- Tauri 2 + React + TypeScript desktop scaffold.
- Minimal Rust host that opens the UI.
- Python 3.12 media-worker package with a testable health function, but no HTTP lifecycle yet.
- `pnpm`, Cargo, and `uv` lockfiles.
- Repository formatting, linting, type-checking, and test commands.
- GitHub Actions for Windows and a fast Linux validation lane where applicable.
- Approved license files: AGPL application/worker, Apache schema/SDK, CC BY documentation.
- CODEOWNERS placeholder, pull-request template, issue templates, DCO check, and dependency-update configuration.
- Architecture decision record template.

## Out of scope

- Worker IPC, database, FFmpeg, import, media playback, and product UI.
- Release signing and installers.

## Implementation steps

1. Create the monorepo directories described in specification section 9.3.
2. Pin supported Node, Rust, and Python versions in toolchain files.
3. Add root commands for `format`, `lint`, `typecheck`, `test`, and `build`.
4. Add one smoke test per language/runtime.
5. Configure CI caching without caching user data or secrets.
6. Add licenses and SPDX headers/guidance.
7. Add ADR-0001 documenting the accepted multi-process architecture.
8. Update README development-status and local setup sections with commands that actually exist.

## Acceptance criteria

- A clean checkout can install dependencies and run every root validation command.
- Desktop window launches and displays a planning-stage placeholder.
- Python, Rust, and TypeScript smoke tests pass.
- CI runs on pull requests and reports failures per toolchain.
- No generated build output is committed.
- License boundaries are clear in directory-level notices.

## Required validation

- Run root formatting check.
- Run root lint and type checks.
- Run all smoke tests.
- Run a production desktop build on the primary development OS.
- Confirm all README commands from a clean environment or documented clean container.

## Handoff

List pinned tool versions, root commands, CI jobs, license choices, and any platform setup not automated. Update the M00 completion ledger entry.

