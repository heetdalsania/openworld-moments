# M38 — macOS UX and accessibility validation

Manual checks for [M38](./M38-macos-ux-accessibility-and-docs.md) on a physical Mac,
with the installed ad hoc build. Results are recorded in the
[M38 handoff](./M38-handoff.md#physical-checks); this page says how to run them.

## Getting the build

Test builds are installed **without a quarantine flag**, as
[macOS development builds](../platforms/macos-development-shell.md#opening-a-shell-on-a-test-mac)
describes: either built on the Mac, or fetched from the pull request's CI run with the
GitHub CLI (files fetched by `gh` are not quarantined). Never remove a quarantine flag
or change Gatekeeper settings to open a build; a browser-downloaded ad hoc build is
expected to be refused.

```bash
gh run download <run-id> --repo heetdalsania/openworld-moments --name macOS-arm64-unsigned-dev --dir ~/owm-m38
```

Open `release-arm64/OpenWorld-Moments_<version>+<commit>_macOS_arm64_adhoc-unnotarized.dmg`
in Finder and drag the app to Applications (choose **Replace** if an older build is
there; the library is kept).

## Checks

Each check starts from the installed app opened from Launchpad or Finder (no Terminal).

| # | Check | Steps | Expected |
|---|---|---|---|
| 1 | Menus and About | Look through the menu bar; open **OpenWorld Moments → About** | Application, File, Edit, View, Window and Help menus as in the [Mac guide](../guides/macos.md#menus-and-keyboard-shortcuts); About shows the version and "Preview build" |
| 2 | Shortcuts | ⌘, ⌘1–⌘4, ⌘F, ⇧⌘I (then Esc), ⌥⌘J, ⌘= / ⌘- / ⌘0, ⌘/ | Each opens its screen or dialog; text size steps 100–200% |
| 3 | Finder | **File → Show Library in Finder**; after a render, **Show in Finder** | Finder opens the library; the render is selected |
| 4 | Open Recent | Open a project, then **File → Open Recent** | The project is listed and opens; **Clear Menu** empties it |
| 5 | Quit question | Start a render, press ⌘Q; choose Cancel, then ⌘Q and Quit | A native alert says a job is running; Cancel keeps the app open |
| 6 | Signing report | **Settings → System check**; **Help → Save Diagnostics Report… → Preview** | "Signature: Signed ad hoc for testing; not notarized by Apple"; the preview's `host.signing.state` is `adhoc`, `gatekeeper` `rejected` |
| 7 | Architecture | System check | "Apple Silicon (arm64) build" and "Right download for this Mac: the Apple Silicon (arm64) DMG" |
| 8 | Setup and permissions | **Help → Run Setup Again**; step 3 *What macOS may ask*; **Open Files and Folders settings** | Seven steps; the button opens Privacy & Security → Files and Folders |
| 9 | Keyboard only | Import a clip, open a session, create a project, render, **Show in Finder**, using only the keyboard | Every step reachable; focus always visible |
| 10 | VoiceOver | ⌘F5, then the same import-to-render path with VoiceOver | Controls and headings are announced by name; job completion is announced; menus and the Quit alert are read |
| 11 | Voice Control | Turn on Voice Control; say "Click Settings", "Click Import", "Show numbers" | The commands act on the named controls |
| 12 | Increase contrast | Accessibility → Display → Increase contrast, theme *Match my system* | Secondary text full strength; outlines stronger |
| 13 | Reduce motion | Accessibility → Display → Reduce motion | No transitions |
| 14 | 200% | **View → Make Text Bigger** to 200%, and macOS Zoom | No horizontal scrolling; everything reachable |
| 15 | Clean account | A new standard macOS user, then setup, folder authorization, import, edit, render, find output with the guides only | Completes without Terminal |
| 16 | Intel | Checks 1–15 on an Intel Mac | As above, with "Intel (x86_64)" |

Install steps that need a notarized, browser-downloaded DMG (the Gatekeeper first-launch
confirmation) are not part of M38; they are checked in
[M39](./M39-dual-platform-release-qualification.md).
