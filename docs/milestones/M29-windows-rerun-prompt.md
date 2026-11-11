# M29 — Windows retest after fixes (session prompt)

Instructions for a Claude Code session on the same Windows 11 test laptop. The
first client run ([report](./M29-windows-client-report.md)) passed M29 but
found one M10 failure and two model-download defects. They are fixed in:

- [#38](https://github.com/heetdalsania/openworld-moments/pull/38): the second
  phone upload was refused as "The computer is out of space."
- [#37](https://github.com/heetdalsania/openworld-moments/pull/37): a cancelled
  model download stayed "Working", and Background jobs said "Nothing partial was
  kept."

This retest repeats only the affected steps. Same rules as the
[first prompt](./M29-windows-session-prompt.md) and the
[runbook](./M29-windows-client-runbook.md): keep the machine clean, work
unelevated, use only a disposable library, and record exactly what you observe.

## Lessons from the first run

- **Start every installer by double-clicking it in File Explorer, and the app
  from the Start menu.** Installers or apps started from this session's shell or
  computer-use tools run inside the Claude app's MSIX container, and their
  results do not count.
- Download artifacts with `gh run download`; record that SmartScreen therefore
  does not evaluate them.

## Steps

1. In the existing clone: `git fetch` and `git switch milestone/M29-windows-qualification`,
   then `git pull`. Confirm `git log` contains the #38 fix (commit message
   starting "M10: keep the live phone staging folder"). If it does not, #38 is not
   merged into this branch yet: tell the tester and stop.
2. Use the newest successful CI run for PR #37 whose commit is the branch head.
   Download `Windows-x64-alpha-candidate` and verify its SHA-256 against
   `checksums.txt` (runbook section 2). Record the run id, commit and hash.
3. If OpenWorld Moments is installed, uninstall it with app data **unchecked**.
   If `%APPDATA%\org.openworldmoments.desktop` contains a library, confirm with
   the tester that it is disposable. The tester then uninstalls again with
   "Delete the application data" ticked, or starts from an empty folder.
4. The tester installs the new candidate from File Explorer and launches it from
   the Start menu. Record the version and the system-check result (runbook
   section 3, briefly).
5. **Model cancel (runbook 5.4):** in Settings, install `base.en` and press
   **Cancel base.en** in Settings while it downloads, **once**. Expected: within
   a few seconds Settings shows the job as cancelled with **Resume install**,
   with no second cancel. Background jobs says the partial download is kept
   (not "Nothing partial was kept"). The `.part` file remains and is not active.
   Then **Resume install**: it must complete and show "Verified installed".
   Remove `base.en` afterwards.
6. **Phone upload (runbook section 8), on a Private network:** upload **at least
   three** videos one after another in the same session. Include one of about
   2 MB or larger, and send one after an earlier one has finished importing.
   Expected: every video is added to the library, with no "out of space".
   Re-send one: "Already in the library". Then **I'm done**, and confirm the old
   link is inactive. Record the phone model/OS, any firewall prompt, and the
   results; never record IP addresses, network names or tokens.
7. Append a `## Retest after fixes` section to
   `docs/milestones/M29-windows-client-report.md` with a table per step
   (expected, observed, Pass/Fail), the run id, commit and hash. Keep the
   original results unchanged.
8. If steps 4–6 all pass:
   - In `docs/milestones/M29-handoff.md`, replace the "Windows 11 client run …
     did not fully pass" known limitation with a short note that the retest
     passed after #37/#38 (keep the 6.2/6.3 maintainer-decision note), and turn
     "Remaining qualification gate" into a "Client qualification" summary that
     links the report.
   - In the `MILESTONES.md` ledger, set **M29** to Complete (PR #37, link the
     report) and **M10** to Complete (remove "Pending: real-phone smoke test",
     cite the retest and #38).
   - In `README.md`, update Project status and the M29 and M10 rows. Change
     "Current next step" to the next milestone `MILESTONES.md` shows as unblocked.
   - Commit with sign-off (`git commit -s`), push, and run `gh pr ready 37`.
     Never merge.

   If anything fails, record it, leave the ledger unchanged, commit and push the
   report only, and tell the tester.
9. Delete the scratch folder and give the tester a short summary with the PR link.
