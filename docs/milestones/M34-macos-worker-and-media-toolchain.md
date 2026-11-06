# M34 — macOS worker and media toolchain

## Objective

Bundle architecture-matched media-worker, FFmpeg, FFprobe, and optional analysis dependencies so the macOS app needs no Homebrew, system Python, or user shell configuration.

## Dependencies

M18, M29, and M33 merged.

## Required context

Read specification sections 9.1, 9.2, 11, 15.3, and the macOS delivery plan.

## In scope

- Native Apple Silicon and Intel worker executables.
- Architecture-matched FFmpeg and FFprobe sidecars.
- Packaged Python/runtime libraries required by implemented detectors.
- Optional architecture-specific OCR, ONNX, and transcription artifacts through the model manager.
- Bundle-relative sidecar discovery and launch.
- Checksums, license inventory, SBOM inputs, and architecture verification.

## Out of scope

- VideoToolbox optimization, signed release bundles, automatic updates, and Mac App Store packaging.

## Implementation steps

1. Select a reproducible worker-freezing strategy for both architectures.
2. Build pinned worker and media sidecars on native CI runners.
3. Resolve every executable relative to the application bundle.
4. Extend the model catalog with platform/architecture compatibility and checksums.
5. Reject wrong-architecture or quarantined/corrupt optional artifacts with actionable errors.
6. Generate dependency/license inventory and SBOM components per architecture.
7. Exercise worker start, health, crash recovery, analysis, and CPU render from the app shell.

## Acceptance criteria

- A clean Mac with no developer tools can start the bundled worker and probe/render a fixture.
- Apple Silicon execution does not invoke Rosetta; Intel execution contains no ARM-only binary.
- The system doctor reports every bundled tool's version, hash, origin, license, and architecture.
- Missing/corrupt sidecars fail visibly without hanging the host.
- Optional models cannot install on an incompatible architecture.
- Windows packaging and model-catalog behavior remain compatible.

## Required validation

- Mach-O architecture audit of every executable and dynamic library.
- Worker lifecycle, FFprobe, CPU render, corruption, missing tool, Unicode path, and cancellation tests on both architectures.
- SBOM-to-bundle inventory comparison.

## Handoff

Document freeze/build tools, dependency versions, bundle layout, sidecar launch rules, model-catalog changes, license findings, architecture-audit output, artifact sizes, and known native-library limitations. Update M34.
