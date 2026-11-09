## Milestone handoff

- Milestone: M29 — Windows packaging and model manager
- Outcome: Planning review only; M29 is **not complete**. Implementation stopped
  before code changes because the existing libx264 requirement and LGPL packaging
  policy need an explicit decision. The proposed smallest correction retains the
  merged encoders and accepts a narrowly scoped GPL FFmpeg distribution with
  matching source, build instructions and notices.
- Files and modules changed:
  - `docs/architecture/adr/0007-windows-ffmpeg-packaging.md`: evidence, proposed
    exception, alternative, restart gate and unchanged Windows validation.
  - `OPENWORLD_MOMENTS_BUILD_SPEC.md`: proposed, explicitly pending exception and
    consistent licensing-risk wording.
  - M29 brief, `MILESTONES.md` and README: planning-review status, corrected context
    references and the existing M18 model-manager dependency.
- Public contracts or migrations: None. No runtime or installer behavior changed.
- Commands run:
  - Repository/dependency inspection, `git fetch origin`, dependency ancestry,
    changed-document local-link checks and `git diff --cached --check`.
  - `uv sync --all-packages --locked --link-mode copy` into a fresh temporary
    environment outside Documents.
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`, with
    `UV_PROJECT_ENVIRONMENT` and `OWM_WORKER_PYTHON` selecting that environment.
- Test and validation results:
  - Full repository gate passes: formatting, ESLint/Clippy/Ruff, REUSE, TypeScript
    and mypy, all tests and generated-contract drift.
  - Worker **1,085 passed, 1 skipped** (existing Windows-only junction test on
    macOS); Python contracts **336**, TypeScript contracts **364**, desktop
    **244**, Rust **50** passed.
  - The original local environment repeatedly acquired hidden flags on workspace
    `.pth` files: the first attempt failed imports during mypy; the next passed
    type checks but failed nine fresh-worker tests with the same missing-contracts
    import. A fresh locked environment restored the imports and passed the whole
    gate. No test, source, timeout or import-path workaround was committed.
  - No Windows installer, model download, clean VM or release qualification was
    run or is claimed. Hosted CI status is recorded in the planning PR.
- Decisions made: No license-policy exception accepted on behalf of maintainers.
  ADR-0007 is a proposal requiring acceptance and a planning merge before code.
- Known limitations:
  - Release worker discovery still requires `OWM_WORKER_PYTHON`; the development
    environment and PATH media tools are not a clean-machine package.
  - Existing Windows CI builds without installers. A green run of that workflow
    cannot satisfy M29's clean Windows client lifecycle criterion.
  - Signed model catalog, resumable downloads, model-manager UI, runtime pinning,
    installer lifecycle and all M29 implementation remain outstanding.
- Follow-up milestones affected: M30, M31 and M33 remain dependent on actual M29
  completion. M32/M34 and later release gates must not consume this proposal as
  a packaged-runtime handoff.
- Screenshots, reports, or artifacts: Documentation proposal only; no generated
  media, binary, model, library, private path or credential is committed.

### Dependency evidence

All dependency merge commits are ancestors of current `origin/main`:

| Milestone | Merged PR | Merge commit | Handoff inspected |
|---|---|---|---|
| M03 | [#7](https://github.com/heetdalsania/openworld-moments/pull/7) | `c3f983c` | PR handoff, worker architecture and ADR-0004 |
| M08 | [#13](https://github.com/heetdalsania/openworld-moments/pull/13) | `d89bf80` | PR handoff and derived-media architecture |
| M18 | [#24](https://github.com/heetdalsania/openworld-moments/pull/24) | `200aaed` | `M18-handoff.md` and model registry/adapter |
| M24 | [#30](https://github.com/heetdalsania/openworld-moments/pull/30) | `7a4233c` | `M24-handoff.md` and CPU encoder registry |

### Required next action

Maintainer accepts the GPL packaging exception or requests the separately scoped
LGPL encoder prerequisite. Then merge the corrected plan and resume M29. Keep
the ledger out of Complete until every original acceptance criterion and
required validation is satisfied.
