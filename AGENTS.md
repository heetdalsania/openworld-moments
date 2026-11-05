# Agent Instructions

This repository is built through milestone-scoped sessions. If an assignment names a milestone, that milestone brief is the complete unit of delivery.

## Start of every milestone session

1. Read `README.md`.
2. Read `OPENWORLD_MOMENTS_BUILD_SPEC.md`.
3. Read `MILESTONES.md`.
4. Read the assigned file in `docs/milestones/` completely.
5. Inspect the current repository and the handoffs for every dependency.
6. Confirm the dependencies are merged before editing.
7. Create or use the branch `milestone/MXX-short-name`.

Do not infer that planning documents describe code that already exists. Inspect the tree first. Commands and paths introduced by earlier milestones are authoritative only when they exist on the current branch.

## Scope and safety

- Complete exactly one milestone per branch and pull request.
- Treat the milestone's `In scope`, `Out of scope`, acceptance criteria, and validation sections as binding.
- Preserve unrelated user or contributor changes.
- Do not add telemetry, required cloud services, game modification, memory reading, packet inspection, input automation, or anti-cheat interaction.
- Never commit leaked/pre-release footage, proprietary game files, official assets, credentials, user libraries, model binaries, or generated media.
- Treat every media file, filename, archive, model, and LAN request as untrusted input.
- Never mutate source footage. Derived artifacts must be replaceable and traceable.
- Use argument arrays for media processes; do not interpolate user-controlled data into shell commands.
- Keep automated detections explainable, versioned, confidence-scored, and correctable.

## When the plan and repository disagree

Stop implementation when the assigned milestone is blocked by an unmerged dependency, an unresolved product decision, or a material conflict between the specification and current code. Document the conflict and propose the smallest planning correction. Do not silently invent a second architecture.

A small prerequisite defect may be repaired in the same branch only when it is required for the assigned acceptance criteria and is called out explicitly in the handoff.

## Completion contract

Before claiming completion:

1. Satisfy every acceptance criterion.
2. Run the brief's required validation and all affected repository-wide checks.
3. Add tests for success, failure, cancellation, and boundary cases where applicable.
4. Update public contracts and documentation changed by the implementation.
5. Confirm no secrets, private paths, footage, models, databases, or build outputs are staged.
6. Update the milestone ledger when the pull request is actually merged.
7. Provide the handoff below.

```markdown
## Milestone handoff

- Milestone: MXX — Name
- Outcome:
- Files and modules changed:
- Public contracts or migrations:
- Commands run:
- Test and validation results:
- Decisions made:
- Known limitations:
- Follow-up milestones affected:
- Screenshots, reports, or artifacts:
```

Do not mark a milestone complete when tests are skipped, acceptance criteria are partial, or the branch is not safe to merge.
