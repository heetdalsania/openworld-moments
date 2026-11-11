# M29 — Windows test-machine session prompt

Instructions for a Claude Code session on the Windows 11 test laptop. It finishes
M29 (and the pending M10 phone test) of `heetdalsania/openworld-moments`. The
session runs in the tester's `WindowsTest` folder, under a standard (non-admin)
local account. Work autonomously; stop only when the tester needs to click, look
at the screen or use their phone.

## Setup

1. Install only the GitHub CLI if it is missing (`winget install --id GitHub.cli`),
   then run `gh auth login` with the tester. Git for Windows is allowed. Do **not**
   install Python, uv, Node, pnpm, Rust, FFmpeg, MSYS2, Tesseract or anything
   else, and do not edit PATH: the machine must stay clean.
2. Clone the repository into the current `WindowsTest` folder on branch
   `milestone/M29-windows-qualification`
   (`git clone -b milestone/M29-windows-qualification https://github.com/heetdalsania/openworld-moments.git`),
   and set `git user.name` and `user.email` for that clone (ask the tester).
3. Read `AGENTS.md`, `docs/milestones/M29-handoff.md`,
   `docs/architecture/windows-packaging.md` and
   `docs/milestones/M29-windows-client-runbook.md` completely.
4. Draft PR #37 builds the installers. Run `gh pr checks 37`. If "Desktop
   production build (Windows)" is still pending, tell the tester and wait; if it
   failed, stop and report the failure.

## Execute

5. Follow `M29-windows-client-runbook.md` sections 1–8 exactly and in order.
   Hard stops: the machine is not Windows 11 x64; this account is an
   administrator; an installer checksum does not match; or
   `%APPDATA%\org.openworldmoments.desktop` already exists before step 1.
6. Use computer-use or screenshot tools if this session has them. Otherwise tell
   the tester exactly what to click, one step at a time, and wait for their
   report. Never mark a step Pass without either seeing it yourself or the
   tester's confirmation.
7. On any failure, record the exact message and collect the logs into
   `%TEMP%\owm-qual`, then continue with the steps that don't depend on it. Do
   not try to fix application code on this machine.

## Report and finish

This section replaces runbook section 9's "do not edit the ledger" note.

8. Write `docs/milestones/M29-windows-client-report.md` as runbook section 9
   describes. Before committing, make sure it contains no usernames, absolute
   user paths, IP addresses, network names, tokens, media or screenshots.
9. If every required M29 step passed:
   - `docs/milestones/M29-handoff.md`: replace "Remaining qualification gate"
     with a "Client qualification" summary that links the report; update Outcome
     and Commands run.
   - `MILESTONES.md` ledger: set M29 to Complete, linking PR #37 and the report.
     If section 8 passed, also set M10 to Complete and remove its "Pending" note.
   - `README.md`: update the Project status text and the M29 row, and change
     "Current next step" to the next milestone that `MILESTONES.md` says is
     unblocked.

   If anything failed: leave M29 "In progress", record the failures in the
   report and the handoff's Known limitations, and do not mark anything complete.

10. Commit with sign-off (`git commit -s`) and push. Only if everything passed,
    mark the PR ready (`gh pr ready 37`). Never merge it.
11. Delete `%TEMP%\owm-qual`. Then give the tester a summary: results per
    section, the PR link, and anything still left to do.
