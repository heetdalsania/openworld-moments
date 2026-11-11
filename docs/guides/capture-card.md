# Capture cards and PC recordings

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64).
> **Last checked:** 2026-11-11 (M31).

If you record your console with a capture card, or record on a PC with software such as
OBS, the recordings are ordinary video files. OpenWorld Moments imports them like any
other file. It does not control the capture card or the recording software.

## Recommended recording settings

These settings import fastest and play back without conversion:

- **Container:** MP4 or MKV. MOV, M4V, WebM, TS and M2TS also work.
- **Video:** H.264 or HEVC (H.265), at the resolution and frame rate you play at.
- **Audio:** AAC, 48 kHz. Keep game audio and chat on separate tracks if your software
  allows; the editor previews the first audio track.
- **HDR:** supported. HDR clips are tone-mapped to standard range for playback and
  renders.
- **Remux MKV recordings to MP4 when you can.** Some programs can do this
  automatically after recording; either file works for import.

## Import the recordings

Use either method:

- **One-off:** **Import → Choose folder…** and pick the recordings folder.
- **Automatic:** add the recordings folder as a [watched folder](./watched-folders.md)
  with the source set to **Capture card** (or **OBS**). Each new recording is imported
  about 10 seconds after the software finishes writing it.

Imports **keep files where they are (reference)** unless you chose **copy into the
library (managed)**. With reference imports, keep the recordings where they are, or the
app shows them as missing.

## Tips

- **Record in sessions.** Clips recorded close together are grouped into one session,
  and footage that repeats across clips is detected and played once.
- **Watch the free space.** Long recordings are large. The system check warns when the
  library drive is low; see [Troubleshooting](./troubleshooting.md).
- **Split recordings are fine.** Software that splits long recordings into parts is
  handled: the parts form one session.
