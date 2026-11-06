# M35 — macOS files, permissions, and lifecycle

## Objective

Make imports, watched folders, external drives, application storage, phone transfer, and background processes behave safely under macOS permissions and lifecycle events.

## Dependencies

M07, M10, M33, and M34 merged.

## Required context

Read specification sections 6, 9.2, 15, and 18 plus the macOS delivery plan.

## In scope

- Native file/folder selection and remembered user-authorized locations.
- Application Support, Caches, Logs, temporary staging, and export paths.
- Watched-folder behavior for local folders, OneDrive/File Provider folders, and external drives.
- Permission revocation, stale paths, disconnect/reconnect, and cloud-placeholder states.
- Application quit, forced worker exit, sleep, wake, and restart recovery.
- macOS firewall/local-network onboarding for temporary phone upload.
- Keychain-backed storage for secrets that must persist.

## Out of scope

- Mac App Store sandboxing, iCloud synchronization, Finder extensions, and background launch agents.

## Implementation steps

1. Map canonical and derived storage to standard macOS directories.
2. Route import, watch, export, and relocation through native selection flows.
3. Add explicit authorization state and reauthorization UX for unavailable locations.
4. Stabilize File Provider placeholders before import and surface download-required states.
5. Reconcile jobs and watched folders across sleep/wake, quit, crash, and drive reconnect.
6. Explain and test local-network/firewall behavior before enabling QR upload.
7. Add recovery fixtures for permissions and removable/cloud storage.

## Acceptance criteria

- The app never scans a directory that the user did not select or configure.
- Permission loss, offline drives, and cloud placeholders produce recoverable states without record deletion.
- Watched folders resume without duplicate imports after restart and sleep/wake.
- Temporary phone upload remains disabled by default and closes completely when its screen/session ends.
- Application-owned data appears only in documented macOS locations.
- Quit/cancellation leaves no job falsely marked complete and no source file modified.

## Required validation

- Local, external-drive, OneDrive/File Provider, Unicode, long-path, offline, and permission-revocation cases.
- Sleep/wake, force-quit, worker-crash, and relaunch recovery tests.
- Phone upload firewall, binding, expiry, rejection, and cleanup tests on a clean Mac.

## Handoff

Document paths, permission states, watched-folder persistence, File Provider behavior, lifecycle events, Keychain usage, firewall UX, test hardware, and remaining OS-specific limitations. Update M35.
