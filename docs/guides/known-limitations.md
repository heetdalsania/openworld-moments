# Known limitations

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64).
> **Last checked:** 2026-11-11 (M31).

This is an alpha. These are the limits we know about, so nothing here should surprise
you. Each is tracked by the milestone named in brackets.

## Platform and installation

- **Windows only for now.** macOS builds are planned (M33–M38).
- **The installer is not signed.** Windows SmartScreen may warn or, under some company
  policies, block it. Check the download with `checksums.txt`.
- **No automatic updates.** Install new versions by hand after checking them.
- **English only.** The interface and guides are not translated.

## Getting clips in

- **No direct console connection, ever.** The app never connects to an Xbox, a
  PlayStation, or their services. Xbox clips arrive through OneDrive; PlayStation clips
  through your phone.
- **Phone transfer uses plain HTTP** on your local network, protected by a secret link
  rather than encryption. Use it only on a network you trust.
- **OneDrive files that are only in the cloud wait** until OneDrive downloads them.
- **The library location is fixed** in the alpha
  (`%APPDATA%\org.openworldmoments.desktop\library`). Reference imports leave your files
  where they are; managed imports copy them into this folder.

## Detection and suggestions

- **Detections are drafts.** Detected moments and story suggestions come from
  explainable rules with confidence scores, not certainty. Review them; corrections are
  kept.
- **Game profiles are unvalidated.** HUD regions and text for a specific game must be
  calibrated from legitimate post-release captures. Until then, detection quality for
  that game is unknown.
- **Speech transcription needs a separate engine.** Models can be installed from
  Settings once you allow downloads, but the whisper.cpp program itself must be
  installed separately ([guide](./transcription.md)).
- **Audio events are supporting evidence only**, never highlights on their own.

## Editing and rendering

- **Captions and on-screen text are not drawn into renders yet.** Renders that would
  need them ask you to confirm leaving them out.
- **Renders stay in the library.** Use **Show in folder** to find one, then copy it
  wherever you like.
- **Hardware encoding** is used only when its test encode passes; otherwise renders use
  the CPU encoder, which is slower.
- **Up to 120 pieces** per render.
- **FCPXML export is experimental.** Check it in your editor before relying on it.

## Privacy review

- The privacy and spoiler review is a checklist with blur and mute tools. It does not
  recognize people, guarantee that personal information is found, or give legal
  clearance.

## Accessibility

- Keyboard-only use and the automated checks are covered; screen-reader testing on
  Windows (Narrator, NVDA) is still to be done. See the
  [support matrix](./accessibility.md#support-matrix). There is no formal WCAG
  certification.
- Drawing calibration regions works with the keyboard but is easiest with a mouse.
