# M38 — macOS UX, accessibility, and documentation

## Objective

Make the supported macOS application feel understandable and native enough for a nontechnical user to install, authorize, operate, diagnose, and remove.

## Dependencies

M31, M35, and M37 merged.

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

## Out of scope

- Full localization, formal Apple accessibility certification, Mac App Store metadata, and support for obsolete macOS releases.

## Implementation steps

1. Add and test native menu/shortcut/lifecycle integrations.
2. Adapt onboarding and system-doctor explanations to macOS permissions and architecture.
3. Fix semantic names, focus order, announcements, contrast, motion, and keyboard conflicts.
4. Test every primary task with VoiceOver and a black/screen-curtain workflow where practical.
5. Add architecture-selection, installation, update, troubleshooting, and uninstall guides.
6. Add redacted diagnostics preview with macOS capability and notarization fields.
7. Run a fresh-user usability test on both Mac architectures and revise confusing steps.

## Acceptance criteria

- A first-time user selects the correct DMG, installs, authorizes folders, imports, edits, renders, and finds output without a terminal.
- Import-to-render is possible with keyboard and VoiceOver on Apple Silicon.
- Menus and shortcuts follow macOS conventions without breaking Windows mappings.
- Permission recovery never recommends disabling Gatekeeper, quarantine, firewall, or system protections.
- Diagnostics exclude footage, transcripts, tokens, user names, and absolute personal paths by default.
- Every macOS guide is validated from a clean user account on its stated OS/architecture.

## Required validation

- Manual keyboard, VoiceOver, Voice Control smoke, increased contrast, reduced motion, and 200% zoom checks.
- Menu/shortcut, permission recovery, architecture-selection, documentation-link, and diagnostic-redaction tests.
- Clean-account usability runs on Apple Silicon and Intel.

## Handoff

Document menus/shortcuts, accessibility matrix, tested assistive technologies, onboarding states, permission guidance, guide validation dates, clean-user findings, screenshots, and remaining UX exceptions. Update M38.
