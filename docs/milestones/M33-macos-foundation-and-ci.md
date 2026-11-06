# M33 — macOS foundation and CI

## Objective

Establish an explicit macOS platform contract, architecture-aware build configuration, and continuously tested native application shell for Apple Silicon and Intel.

## Dependencies

M24 and M29 merged.

## Required context

Read specification sections 9, 15, 16, and 22 plus `docs/platforms/macos-delivery-plan.md`.

## In scope

- macOS 14+ support policy for `aarch64` and `x86_64`.
- ADR for separate native DMGs, direct distribution, Hardened Runtime, and initial non-App-Sandbox delivery.
- Host platform abstraction audit for paths, dialogs, keychain, processes, menus, and lifecycle.
- Architecture-aware build metadata and artifact naming.
- Pinned Apple Silicon and Intel GitHub Actions build/test jobs.
- macOS system-doctor capability surface.
- Unsigned development application shells for both architectures.

## Out of scope

- Packaged Python/FFmpeg sidecars, complete media workflows, signing, notarization, and release publication.

## Implementation steps

1. Verify the OS floor against every locked native dependency and record the result.
2. Add a platform capabilities contract without scattering OS conditionals through product modules.
3. Implement standard macOS application, cache, log, and temporary-directory resolution.
4. Configure native `aarch64-apple-darwin` and `x86_64-apple-darwin` builds.
5. Add pinned CI jobs with architecture and dependency-cache isolation.
6. Add architecture/version reporting to diagnostics and the system doctor.
7. Produce and launch unsigned development shells on physical Macs of both architectures.

## Acceptance criteria

- Both native Tauri hosts compile from a clean checkout using documented commands.
- CI reports each architecture independently and verifies the produced Mach-O architecture.
- The application uses macOS-standard data directories and does not require a shell `PATH`.
- Platform-specific behavior is behind reviewed interfaces with Windows behavior unchanged.
- An unsigned development shell launches on one supported Apple Silicon Mac and one supported Intel Mac.
- The support matrix and rationale are documented without claiming media-workflow parity.

## Required validation

- Formatting, linting, type checks, Rust/TypeScript tests, and both macOS build jobs.
- Physical launch/version-report smoke test on both architectures.
- Windows regression build for all platform-abstraction changes.

## Handoff

Document the verified OS floor, architecture matrix, ADR decisions, platform interfaces, CI runner labels, build commands, physical test hardware, and remaining packaging gaps. Update M33.
