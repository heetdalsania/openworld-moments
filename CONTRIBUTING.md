# Contributing to OpenWorld Moments

OpenWorld Moments uses milestone-scoped development. Each implementation branch should complete exactly one milestone from [MILESTONES.md](./MILESTONES.md).

## Before starting

1. Read the product specification.
2. Select a milestone whose dependencies are merged.
3. Read its individual brief completely.
4. Confirm no one else is actively implementing it.
5. Create a branch named `milestone/MXX-short-name`.

## Scope rules

- Implement only the selected milestone and necessary prerequisite fixes.
- Preserve user files and existing unrelated work.
- Do not refactor unrelated modules.
- Do not add cloud services, telemetry, game automation, or proprietary assets.
- Do not commit real gameplay footage unless the fixture policy explicitly allows it.
- Record architectural deviations in an ADR or milestone handoff.

## Completion requirements

A milestone is complete only when:

- Every acceptance criterion in its brief is met.
- Required automated tests pass.
- Formatting, linting, type-checking, and build checks pass.
- Relevant documentation is updated, including the README's **Project status** and **Current next step** sections and the `MILESTONES.md` ledger row.
- No secrets, private footage, or generated build artifacts are committed.
- A handoff note is added to the pull request or final commit message.

## Handoff format

```markdown
## Milestone handoff

- Milestone: MXX — Name
- Summary:
- Files and modules changed:
- Commands run:
- Test results:
- Decisions made:
- Known limitations:
- Follow-up milestones affected:
- Screenshots or artifacts:
```

## Local checks and sign-off

Run `pnpm check` before opening a pull request. Setup steps and per-toolchain
commands are in the README's "Local development" section.

Every commit needs a Developer Certificate of Origin sign-off (`git commit -s`).
CI fails pull requests with unsigned commits. New files need license
information; see [docs/contributing/licensing.md](./docs/contributing/licensing.md).

Architecture changes need an ADR in [docs/architecture/adr/](./docs/architecture/adr/).

## Pull requests

The pull-request title should begin with the milestone identifier, for example:

```text
[M04] Add safe reference and managed-copy imports
```

Keep commits understandable and do not force-push after review begins unless requested. Reviewers should evaluate the milestone's acceptance criteria before style preferences.

## Generated files

Generated contracts, migrations, and lockfiles should be committed when the milestone specifies them. Media proxies, local databases, models, application logs, exports, and user footage must not be committed.

## Legal and safety

Do not contribute leaked footage, game files, official artwork, extracted assets, anti-cheat bypasses, memory readers, packet inspectors, or input automation. Compatibility work must operate on user-provided video and audio only.

