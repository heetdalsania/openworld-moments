# Captions and audio controls (M23)

M23 extends the [focused editor](./focused-editor.md) with editable captions and
non-destructive audio controls. Sources and session transcripts remain unchanged.
No model, engine, cloud request or download is started by the caption editor.

## Project contract and commands

Contracts **1.17** add optional `Project.caption_settings`:

```json
{
  "preset": "high-contrast",
  "region": [0.08, 0.06, 0.84, 0.18],
  "burn_in": false,
  "sidecar": "none"
}
```

`preset` is `high-contrast` or `compact`. `region` is a normalized output-frame
rectangle, checked inside the frame in TypeScript and Python. `sidecar` is
`none`, `srt`, `vtt` or `both`. Missing settings use the example defaults. Existing
1.x Project/editor documents remain readable; model version stays 1 and no SQL
migration is needed. The existing JSON autosave, previous recovery document,
portable export and revision-conflict rules preserve these fields.

New pure M21 commands in `editor.ts`:

- `captions`: add, update text/times, remove, split with explicit time/left/right
  text, merge adjacent array entries with a newline, or replace with an explicit
  list. Results sort by start then end; negative/empty/outside ranges and text over
  1,000 characters are rejected atomically. Overlapping cues remain allowed for
  compatibility. UI split divides saved text by Unicode code point; apply draft
  text changes before splitting. Undo/redo restores exact text and settings.
- `caption-settings`: replace validated placement/style/output intent.
- `audio`: project gain, mute/unmute range, range gain and clear range gain.

All times are integer project-relative milliseconds, with exclusive ends. M21's
existing trim/split/reorder/delete retiming carries captions and audio ranges
with retained source content, including repeated instances. UI input drafts stay
local until Apply and survive validation failure and unrelated audio/metadata
commands. Actual content changes reset their baselines, so undo cannot revive stale
input and keyboard focus stays in place. Global shortcuts ignore fields;
Tab, native buttons, labelled numeric controls and selects cover every operation.

## Transcript initialization

`CaptionPanel` reads M18's existing transcript only after **Use session
transcript**. Replacing existing captions needs an explicit checkbox. Segment
mode copies each intersecting sentence; word mode uses each timed word, falling
back to the segment when it has no words. Asset ID plus source coordinates map
intersections into every retained project cut. Session time is never copied
straight into a reordered project. Missing session identity, unresolved/replaced
bindings, no intersecting text and excessive cue counts fail visibly.

Loading can be cancelled. Input changes also cancel a pending replacement.
Navigation, cancellation or a concurrent project edit
prevents the pending response from replacing current captions. Imported captions
are independent text copies: deleting/rebuilding the session transcript does not
remove/correct project copies. No transcript text is logged. The panel states
this retention behavior and asks users to review automatic text/timing.

## Caption preview and protected regions

`CaptionPreview` shows active plain-text cues and a dashed safe-area rectangle in
output-frame coordinates, including when burn-in is off. High contrast uses a
larger bold system font with dark backing; compact uses a smaller font. Top,
middle and bottom placements preserve horizontal margins. The primary caption
marker strip shows the first 200 cues; the labelled selector reaches all 10,000.
Caption text/preview never interprets HTML or style instructions.

An explicitly selected existing profile stores M21's profile ID/version pair.
`getCalibration` shares the existing calibration query cache and uses the current
local effective regions. Preserved zones and named HUD/chat/subtitle regions are
mapped through the current source's upright fit/letterbox geometry. Intersections
with the caption rectangle warn visibly; moving the caption rectangle updates
that warning. A missing profile or changed version is stated explicitly.
This is current-preview placement guidance, not a privacy or game-compatibility
certification. M24/M25 must implement final rendering/layout behavior.

## Sidecars and native save

`captions.ts` serializes a bounded plain-text subset of SRT/WebVTT as UTF-8:
sequential numbers, exact integer milliseconds, sorted cues, preserved Unicode and
multiline text. SRT stores raw text; VTT escapes `&`, `<`, `>` entities.
SRT uses comma milliseconds;
VTT uses periods and a `WEBVTT` header. Hours can exceed 99. Empty lists are valid.
The matching parser round-trips this subset, including BOM and CRLF input. It
refuses VTT markup, cue settings and unsupported timing/header syntax. SRT text
is retained literally by this parser; external SRT players may interpret
HTML-like markup differently, so use VTT when literal angle brackets matter. This parser is
not a general subtitle-file import UI.

Empty/blank lines, control characters, unpaired surrogates, invalid times, more
than 10,000 cues or output over 4 MiB fail without changing project text. Caption
text containing intentional blank lines remains saved in the project; users must
split/correct it before a sidecar can represent it without ambiguity.

**Save SRT/VTT sidecar…** serializes the current local draft and invokes only
`caption_export {text, format}`. The native host bounds the payload and accepts
only `srt`/`vtt`, then opens a save dialog with a fixed suggested name. The webview
cannot supply a destination path. Existing M15 exclusive-create writing refuses
existing files, symlinks, hardlinks and wrong extensions. Cancellation returns
false; write errors preserve the project. The format selection and burn-in intent
are saved even though video rendering belongs to M24.

## Audio model and preview

Existing `Project.audio` uses decibels in **−60 to +24 dB**. Zero is unchanged;
linear amplitude is `10 ** (gain_db / 20)`. Non-overlapping gain ranges **replace**
project gain inside their bounds. Mute takes precedence. Selected-cut controls
write exactly that cut's current project interval. Partial clear/unmute keeps
pieces outside the chosen range; overlapping mutes are unioned. The waveform
track shades muted intervals and the audio panel reports the playhead state.

`EditorAudio` creates one Web Audio graph per mounted video pair on an explicit
play gesture: media-element source → gain → destination. Both gain nodes receive
the current timeline gain; the existing player pauses/mutes the standby video.
Caption/audio-only changes do not restart the source decoder. Closing the editor
pauses playback and closes its AudioContext. Stale pending play promises cannot
restart a closed/seeking preview. If Web Audio is unavailable, native volume can
attenuate/mute, while amplification is refused visibly.

Preview updates follow the media/playhead callbacks and animation frames, not a
sample-accurate audio render clock; background throttling/buffering may delay
range transitions. M24 must compile exact stored intervals into output audio.
Positive gain may clip. Preview uses the existing first audio stream and never
claims voice-chat/music separation; the mixed-audio warning is always visible.

## Evidence and references

- Command/serializer/golden tests: `captions.test.ts`, `editorAudio.test.ts`,
  `src/testing/captions.srt` and `.vtt`.
- Component keyboard/edit/reload, cancellation/conflict, warning and save-dialog
  outcome tests: `EditorView.test.tsx`.
- Worker save/reopen/recovery and unchanged source bytes: project service tests.
- Manual Chromium fixture: `tests/editor_browser.py --captions`; it uses the real
  worker, FFmpeg and M18 test-double transcription in a temporary library. No real
  recognition quality is established. Local artifacts are ignored, never shipped.
- [SubRip format description](https://www.loc.gov/preservation/digital/formats/fdd/fdd000569.shtml),
  [WebVTT specification](https://www.w3.org/TR/webvtt1/),
  [media-element audio sources](https://developer.mozilla.org/en-US/docs/Web/API/MediaElementAudioSourceNode),
  [gain nodes](https://developer.mozilla.org/en-US/docs/Web/API/GainNode).
