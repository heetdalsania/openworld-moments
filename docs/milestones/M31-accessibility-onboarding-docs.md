# M31 — Accessibility, onboarding, and documentation

## Objective

Make the alpha understandable and operable without prior project knowledge, a terminal, or pointer-only interaction.

## Dependencies

M22 and M29 merged.

## Required context

Read specification sections 12, 16, 17.3, and 20.

## In scope

- Keyboard-complete primary workflow and visible focus states.
- Semantic labels, screen-reader announcements, contrast, and reduced-motion behavior.
- First-run onboarding for privacy, import methods, optional models, and system checks.
- Xbox OneDrive, PlayStation phone-transfer, watched-folder, and capture-card guides.
- Troubleshooting, diagnostics export, terminology, and known-limitations pages.
- Documentation screenshots and versioned compatibility notes.

## Out of scope

- Full localization, formal WCAG certification, and support for every assistive technology.

## Implementation steps

1. Inventory all primary screens, focus order, shortcuts, and non-text controls.
2. Fix semantic names, keyboard traps, contrast failures, motion, and status announcements.
3. Build skippable first-run onboarding with persistent privacy choices.
4. Write task-based setup and transfer guides using tested current workflows.
5. Add diagnostics export with explicit redaction and preview.
6. Create an accessibility/compatibility test matrix.
7. Run a fresh-user usability pass and revise confusing terminology.

## Acceptance criteria

- Import, review, edit, render, and locate output are possible using only a keyboard.
- Critical progress, error, and completion states are exposed to assistive technology.
- Onboarding accurately states that the app does not run on or modify a console.
- Optional model and LAN features require informed opt-in.
- Diagnostics preview excludes footage, tokens, and personal paths by default.
- Every documented workflow has been followed successfully from a clean test account.

## Required validation

- Automated accessibility checks plus manual keyboard and screen-reader smoke tests.
- 200% zoom, high contrast, reduced motion, and narrow-window checks.
- Documentation link, screenshot, clean-account, and diagnostics-redaction tests.

## Handoff

Document the accessibility matrix, remaining exceptions, tested assistive technologies, onboarding decisions, guide validation dates, screenshots, and usability findings. Update M31.
