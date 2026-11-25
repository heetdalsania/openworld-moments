# M38 — macOS UX, accessibility, and documentation

## Objective

Make the supported macOS application feel understandable and native enough for a nontechnical user to install, authorize, operate, diagnose, and remove.

## Dependencies

M31 and M35 merged, and M37's credential-free signing and DMG pipeline merged
([#58](https://github.com/heetdalsania/openworld-moments/pull/58)). M38 does not
wait for M37's Apple Developer Program enrollment, Developer ID signing or
notarization.

### Planning note (dependency change)

M38 originally waited for all of M37. M37 is blocked only on the maintainer's
Apple Developer Program enrollment. Its DMG layout, Hardened Runtime signing,
install/replace/uninstall behavior and signing report are already on `main` and
are signed ad hoc. Nearly all of M38 (menus, shortcuts, lifecycle, onboarding,
permission guidance, accessibility, diagnostics and guides) needs only an
installed app. M38 therefore starts on the merged pipeline. The one check that
needs a notarized DMG, downloading with a browser and passing Gatekeeper on
first launch, moves to [M39](./M39-dual-platform-release-qualification.md),
which already requires notarized DMGs on clean Macs.

## Required context

Read specification sections 12, 16, 17, and 20 plus the complete macOS delivery plan.

## In scope

- Standard application/File/Edit/View/Window/Help menus and macOS shortcuts.
- Finder reveal, open/recent behavior, quit confirmation, About/version, and diagnostics actions.
- Architecture-aware download/install and first-run onboarding.
- Permission, firewall, external-drive, and File Provider recovery guidance.
- Keyboard-complete primary workflow with macOS conventions.
- VoiceOver, Voice Control, increased contrast, reduced motion, and zoom testing.
- macOS setup, transfer, troubleshooting, update, uninstall, and privacy documentation.
- Download and install guidance written against M37's architecture-labelled DMG layout and
  [macOS signing](../platforms/macos-signing.md) install/uninstall section.

## Out of scope

- Full localization, formal Apple accessibility certification, Mac App Store metadata, and support for obsolete macOS releases.
- Developer ID signing, notarization and the clean-Mac Gatekeeper first-launch check of a
  browser-downloaded DMG (M37 and M39).

## Implementation steps

1. Add and test native menu/shortcut/lifecycle integrations.
2. Adapt onboarding and system-doctor explanations to macOS permissions and architecture.
3. Fix semantic names, focus order, announcements, contrast, motion, and keyboard conflicts.
4. Test every primary task with VoiceOver and a black/screen-curtain workflow where practical.
5. Add architecture-selection, installation, update, troubleshooting, and uninstall guides.
6. Add redacted diagnostics preview with macOS capability and notarization fields.
7. Run a fresh-user usability test on both Mac architectures and revise confusing steps.

## Acceptance criteria

- A first-time user selects the correct DMG from the architecture-selection guidance, and,
  starting from an installed app, authorizes folders, imports, edits, renders, and finds output
  without a terminal. Test builds are installed without a quarantine flag (built on the Mac or
  fetched with `gh run download`), as [macOS development builds](../platforms/macos-development-shell.md#opening-a-shell-on-a-test-mac) describes.
- Import-to-render is possible with keyboard and VoiceOver on Apple Silicon.
- Menus and shortcuts follow macOS conventions without breaking Windows mappings.
- Permission recovery and install guidance never recommend disabling Gatekeeper, removing quarantine, turning off the firewall, or bypassing system protections. Until notarized DMGs exist, the guides say macOS builds are previews and not for general download.
- The diagnostics notarization field reports the bundle's real state (ad hoc, Developer ID, or notarized) and never claims notarization the bundle lacks.
- Diagnostics exclude footage, transcripts, tokens, user names, and absolute personal paths by default.
- Every macOS guide is validated from a clean user account on its stated OS/architecture, except the browser-download and Gatekeeper first-launch steps of the install guide, which M39 validates with notarized DMGs.

## Required validation

- Manual keyboard, VoiceOver, Voice Control smoke, increased contrast, reduced motion, and 200% zoom checks.
- Menu/shortcut, permission recovery, architecture-selection, documentation-link, and diagnostic-redaction tests.
- Clean-account usability runs on Apple Silicon and Intel, using builds without a quarantine flag.

## Handoff

Document menus/shortcuts, accessibility matrix, tested assistive technologies, onboarding states, permission guidance, guide validation dates, clean-user findings, screenshots, and remaining UX exceptions. List the install-guide steps left for M39's notarized clean-Mac check. Update M38.
