# M37 — macOS signing, notarization, and DMGs

## Objective

Produce reproducible, Developer ID-signed, hardened, notarized, stapled DMGs for Apple Silicon and Intel that launch normally under Gatekeeper.

## Dependencies

M30 and M34 through M36 merged. Maintainer signing prerequisites in the macOS delivery plan are available.

## Required context

Read specification sections 15, 19, and 22 plus the complete macOS delivery plan and Apple/Tauri signing references.

## In scope

- Separate native `arm64` and `x86_64` application bundles and DMGs.
- Stable bundle identifier, versioning, icons, metadata, and architecture-labelled filenames.
- Hardened Runtime and reviewed minimum entitlements.
- Inside-out signing of worker, FFmpeg, libraries, host, app, and DMG.
- Protected CI certificate/API credentials.
- Apple notarization, log inspection, ticket stapling, Gatekeeper verification, checksums, and SBOMs.
- Install, upgrade, replace, and uninstall/data-retention behavior.

## Out of scope

- Mac App Store submission, universal DMG, automatic updater, and acquiring the maintainer's Apple account or certificate.

## Implementation steps

1. Audit every nested executable/library and define signing order and entitlements.
2. Configure protected CI import and cleanup of signing credentials.
3. Build and sign architecture-specific `.app` bundles and DMGs.
4. Submit with the supported notarization workflow, retain logs, and fail on warnings requiring action.
5. Staple tickets and verify with `codesign`, `spctl`, architecture audit, and checksum tools.
6. Install downloads on clean Macs with no development identity or previous build.
7. Document certificate rotation, credential revocation, release recovery, and manual verification.

## Acceptance criteria

- Both downloaded DMGs pass signature, notarization-ticket, Gatekeeper, hash, and architecture verification.
- A clean user can drag the app to Applications and launch without Terminal or a security bypass.
- Every nested executable is signed by the intended identity with Hardened Runtime where applicable.
- Signing/notarization secrets never appear in logs, artifacts, caches, or support bundles.
- Replacing the app preserves the library; uninstall instructions distinguish app and user data.
- Failure to notarize or staple prevents publication.

## Required validation

- Clean Apple Silicon and Intel install/launch/upgrade/uninstall runs.
- Tampered app, wrong architecture, expired token, missing nested signature, rejected notarization, and credential-redaction cases.
- Independent artifact checksum, SBOM, `codesign`, `spctl`, and stapler verification.

## Handoff

Document bundle IDs, entitlements, signing order, CI secret names (not values), notarization workflow/log locations, artifact hashes, clean-machine evidence, rotation procedure, and remaining distribution limitations. Update M37.
