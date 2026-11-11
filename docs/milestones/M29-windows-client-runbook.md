# M29 — Windows 11 client qualification runbook

This runbook closes the two remaining Windows-only gates:

- **M29:** clean Windows 11 x64 client lifecycle matrix
  ([packaging guide](../architecture/windows-packaging.md#upgrade-uninstall-and-qualification)).
- **M10:** real-phone upload smoke test on a Windows private network
  ([phone guide](../guides/phone-upload.md)).

It is written so a Claude Code session on the Windows test machine can execute it
with the human tester. Everything else (ledger, README, handoff, PR) is finished
afterwards on the development Mac from the report this runbook produces.

## Rules for the agent on the Windows machine

- Follow `AGENTS.md`. Work on branch `milestone/M29-windows-qualification`.
- **Keep the machine clean.** Do not install Python, uv, Node/pnpm, Rust, FFmpeg,
  MSYS2 or Tesseract, and do not edit PATH. Allowed: Git for Windows (required by
  Claude Code; leave its default "Git from the command line" PATH option) and the
  GitHub CLI (`winget install --id GitHub.cli`). Record both in the report.
- Do not run the repository's build or test commands here. This machine tests the
  shipped installer, not the source tree.
- Only use the dedicated test library. If `%APPDATA%\org.openworldmoments.desktop`
  already exists before step 1, stop and ask the tester.
- Never commit media, databases, installers, screenshots with personal data,
  usernames or absolute user paths. Replace the user profile with `%USERPROFILE%`.
- GUI steps: use computer-use tools if this session has them; otherwise tell the
  tester exactly what to click and ask them to report what they see. Do not mark a
  GUI step passed from a guess.
- Any failure: stop that step, capture the exact message, collect
  `%APPDATA%\org.openworldmoments.desktop\logs` (if present) into the scratch
  folder, record it as **Fail**, and continue with independent steps.

## 0. Machine setup (tester)

1. Preferably create a **standard (non-administrator) local account** under Settings →
   Accounts → Other users, sign in to it, and do everything below from it.
2. Install the Claude app in that account, open Claude Code, and clone the repo
   into `%USERPROFILE%\src\openworld-moments` (checkout the branch above).
3. Authenticate the GitHub CLI: `gh auth login`.

## 1. Preflight (agent)

**Administrator-account exception (accepted by the maintainer).** The tester may
run this from a local administrator account if UAC is on. Every step still runs
unelevated: never choose "Run as administrator", and any UAC prompt from the
installer or app is a Fail. The report must state that the run used an
administrator account with UAC, not a standard user. It must list two
standard-user behaviours this run cannot show: whether a standard user can
approve the M10 Windows Firewall prompt (it normally needs an administrator's
credentials), and WebView2 repair (which needs administrator rights).

Run in PowerShell and record outputs:

```powershell
winver   # tester reads edition/version/build from the dialog
Get-ComputerInfo -Property OsName,OsVersion,OsBuildNumber,OsArchitecture,CsProcessors,CsTotalPhysicalMemory
(Get-CimInstance Win32_Processor).Architecture   # 9 = x64; anything else: stop
whoami /groups | Select-String 'S-1-5-32-544'      # empty = standard user; otherwise record the admin exception
(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System').EnableLUA   # must be 1 (UAC on)
foreach ($t in 'python','python3','py','uv','node','pnpm','ffmpeg','ffprobe','tesseract','bash','gcc') { "$t -> $((Get-Command $t -ErrorAction SilentlyContinue).Source)" }
(Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue).pv
Get-NetConnectionProfile | Select-Object Name,NetworkCategory
```

Pass criteria: Windows 11, x64, UAC on, no developer tools on PATH other
than Git's `git.exe`. A Windows Store `python.exe` alias that only opens the Store
is acceptable — record it. If the processor is not x64 or the OS is Windows 10,
stop: the machine cannot qualify.

## 2. Download and verify the candidate (agent)

Use the newest successful CI run on this branch's PR (or `main` if none):

```powershell
$work = Join-Path $env:TEMP 'owm-qual'; New-Item -ItemType Directory -Force $work | Out-Null
gh run list --repo heetdalsania/openworld-moments --workflow CI --branch milestone/M29-windows-qualification -L 5
gh run download <run-id> --repo heetdalsania/openworld-moments -n Windows-x64-alpha-candidate -D "$work\candidate"
gh run download <run-id> --repo heetdalsania/openworld-moments -n Windows-x64-upgrade-test-only -D "$work\upgrade"
Get-FileHash "$work\candidate\*-setup.exe","$work\upgrade\*-setup.exe" -Algorithm SHA256
```

Compare each hash with the artifact's `checksums.txt` (candidate) or
`SHA256SUMS.txt` (upgrade test). Record the run id,
commit SHA and both hashes. A mismatch is a hard stop.

## 3. Install and first launch (tester, GUI)

1. Double-click the candidate installer in File Explorer. Record every prompt
   verbatim (SmartScreen "Windows protected your PC", unknown publisher). Choose
   **More info → Run anyway** only for this candidate. Expect **no** UAC prompt
   (per-user install); a UAC prompt is a Fail.
2. Keep the default install location; record it (expected under
   `%LOCALAPPDATA%`).
3. Launch from the Start menu icon, not from a terminal.
4. The first-run **system check** must appear. Record its results: storage,
   permissions, loopback, SQLite/FTS5, codecs, CPU test encode, catalog signature,
   runtime inventory, and the WebView2 version shown in Settings.
   Hardware-encoder warnings are acceptable when the CPU path passes.

## 4. Import, playback, project, render (tester + agent)

1. Agent creates a lawful synthetic clip with the **bundled** FFmpeg, by full path
   (this does not add FFmpeg to PATH), in a Unicode folder:

   ```powershell
   $clipDir = Join-Path $work 'Synthetic ✓ 日本語'; New-Item -ItemType Directory -Force $clipDir | Out-Null
   $ff = Get-ChildItem "$env:LOCALAPPDATA" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Where-Object FullName -Match 'runtime\\tools' | Select-Object -First 1
   & $ff.FullName -hide_banner -nostdin -y -f lavfi -i 'testsrc2=size=1280x720:rate=30:duration=20' -f lavfi -i 'sine=frequency=440:duration=20' -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$clipDir\Synthetic capture ✓.mp4"
   Get-FileHash "$clipDir\Synthetic capture ✓.mp4" -Algorithm SHA256
   ```

2. Tester imports it (Import button and drag-and-drop), waits for playback
   preparation, plays it in the clip view and in its session.
3. Tester creates a project from the session, trims it, completes the privacy
   review, and exports **horizontal 1080p30** with the CPU (libx264) encoder.
4. Agent verifies the source clip hash is unchanged and that the export file
   exists and plays (tester opens it in the Windows Media Player / Films & TV app).

## 5. Model manager (tester + agent)

In Settings → Optional speech models:

1. Install `tiny.en`; it must download, verify and become active.
2. Start `base.en`, then turn Wi-Fi off mid-download: the job must fail or pause
   with a readable error and the partial must not be active. Turn Wi-Fi on and
   **Retry**: it must resume (record whether bytes resumed rather than restarted).
3. Start a download with Wi-Fi off: readable offline error, nothing activated.
4. Cancel a download in progress: partial retained, not active.
5. Remove `base.en`; media and transcripts stay.
6. Low-disk and checksum/signature refusal: do not fill the disk or tamper with
   the signed catalog on this machine. Record them as "covered by automated tests"
   and name the tests (`services/media-worker/tests` model-manager tests).

Record optional engine availability (whisper.cpp is not bundled; "unavailable" is
expected and acceptable).

## 6. Repair, upgrade, retention (tester + agent)

1. Agent records hashes of `library\database.sqlite3` (after quitting the app) and
   counts of clips/projects/renders shown in the UI.
2. Tester re-runs the **same** candidate installer (repair). Launch: library,
   project and export are intact.
3. Tester runs the **upgrade-test-only** installer (0.1.0-alpha.29.1). Launch:
   Settings shows the new version; library, project, export, active `tiny.en`
   intact. Agent confirms a pre-upgrade backup exists if the schema changed, or
   records that no migration ran (same schema).
4. Agent confirms the source clip hash is unchanged throughout.

## 7. Uninstall, reinstall, data removal (tester + agent)

1. Quit the app. Agent hashes the database. Tester uninstalls from Settings → Apps
   with the app-data checkbox **unchecked**. Agent verifies the library folder and
   database hash are unchanged and the install folder is gone.
2. Tester reinstalls the **upgrade-test-only** build (0.1.0-alpha.29.1), the
   version that last opened the library; installers refuse downgrades and an older
   app must never open a newer database. Launch: the same library, project and
   export appear.
3. **Disposable data removal:** confirm with the tester that this test library is
   disposable. Uninstall **with** the app-data checkbox; both confirmations must
   list the consequences. Agent verifies the library folder is removed, the
   synthetic source clip outside app data still exists with the same hash, and
   records anything retained (preferences are expected to remain).

## 8. M10 real-phone upload (tester + agent)

Reinstall the upgrade-test-only build first (step 7 removed the library, so
this starts with a new empty one). The laptop and a phone must be on the same
**private** home network (`NetworkCategory` = Private).

1. In the app choose **Import from phone**, pick the Wi-Fi interface, **Show QR
   code**. Record any Windows Firewall prompt and allow **private networks only**.
2. Scan with the phone; the upload page opens. Upload two real phone videos
   (or videos the tester owns) and one non-video file.
3. Expected: videos show progress and are added to the library; the non-video is
   refused; re-sending one video shows "Already in the library".
4. Tap **I'm done**; reloading the page on the phone must show the link inactive.
   Open the screen again and wait out or close it; the old link must not work.
5. Record phone OS/browser, network category, firewall prompt, and results. Do not
   record IP addresses, SSIDs or tokens.

## 9. Report and hand back (agent)

Write `docs/milestones/M29-windows-client-report.md` with one table per section
(step, expected, observed, Pass/Fail), the machine/OS/WebView/processor/RAM
details, CI run id, commit and artifact hashes, unsigned prompts, timings for
import and export, and every failure with its exact message. State plainly that
this is a clean Windows 11 client run, separate from hosted CI.

Then:

```powershell
git add docs/milestones/M29-windows-client-report.md
git commit -s -m "M29: record clean Windows 11 client qualification"
git push
```

Do not edit the ledger, README or handoff here; the Mac session completes those
from the report. Delete `$work` and its contents afterwards.
