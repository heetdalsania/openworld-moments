# Privacy and spoiler review (M28)

Review helps a creator find possible risks before export. It cannot identify people,
certify privacy, clear publishing rights, or guarantee detection. No media, text or
findings leave this computer. There are no new engines, models or dependencies.

## Workflow

1. Open the editor's **Privacy and spoiler review** panel. Save edits and use
   **Scan saved project / refresh review** to inspect current saved evidence.
2. Add optional spoiler words/phrases and labelled project-time ranges. Labels are
   literal, case-insensitive whole words/phrases, never regular expressions. Nothing
   is censored automatically. Recheck manual spoiler ranges after timeline edits;
   an out-of-project range blocks review until edited or cleared.
3. Inspect each finding: category, evidence kind/text, heuristic score, project or
   session interval, and source interval/ROI when available. Project buttons seek
   the editor. Session links open evidence outside the cut, because JSONL exports
   every session event. Unproven old OCR timing uses the entire retained source
   range, explicitly labelled conservative.
4. Choose **Acknowledge risk**, **Ignore / false positive**, or **I manually fixed
   and checked this**. **Unresolved / restore finding** reverses any choice.
   “Fixed” is the creator's attestation, not an automatic redaction check.
5. Use **Mute this range** for transcript/audio findings if appropriate. It writes
   an ordinary M23 mute command, muting the complete mixed track. Use Undo or the
   audio panel to reverse it. Scan the changed saved project again.
6. Add and move rectangular blur regions with numeric fields and keyframes, Apply,
   and check the preview and each rendered aspect ratio. Blurs do not remove text
   from captions, JSON, markers or other metadata exports.
7. Resolve every finding, tick the publishing/consent/spoiler checklist, and save
   review decisions. New renders and project exports require this current review.

The UI says explicitly that review is **not privacy or legal clearance**. Consent,
publishing rights, music and platform rules remain the creator's responsibility.

## Detectors and limitations

`conservative-review/1` reads existing M17 OCR, M18 transcripts/audio evidence,
project captions/text overlays and retained source audio metadata. It performs no
new recognition and downloads nothing. Missing OCR/transcription means less
coverage; the mandatory manual checklist still applies even with zero findings.

| Category | Evidence / rule | Heuristic score |
|---|---|---|
| `phone` | formatted 3-3-4 digit candidate, optional country prefix or parentheses | 0.70 |
| `username` | ASCII `@handle` or explicit username/gamertag/player-ID label | 0.65 |
| `subtitle` | OCR subtitle event or project caption, regardless of vocabulary | 0.60 |
| `spoiler` | user phrase match; mission spoiler metadata; manual range | 0.80 / 0.60 / 1.00 |
| `speech` | transcript or speech-like audio feature; not speaker recognition | 0.50 |
| `mixed_audio` | retained source has audio; may include chat, dialogue or music | 0.35 |

Scores are **not calibrated probabilities**. Bare scores, dates, digit runs and
numeric coordinates deliberately do not match the phone rule. Formatted HUD
numbers can still look like phone numbers. Bare names, many international formats,
non-ASCII handles, obscured text, unrecognized speech and unanalysed footage can be
missed. Subtitles and metadata warnings are intentionally broad. Speech-like music
can be a false positive. No identity recognition, audio separation, automated
censorship, legal clearance, or real-game precision/recall is claimed.

## Contracts, persistence and gate

Contracts **1.22** add `privacy-review`: `PrivacyReview`, `RiskFlag`, `PrivacyConfig`,
`SpoilerRange`, `PrivacyDecision` and `PrivacySummary`. Findings contain stable
hash IDs, categories, bounded evidence, confidence and supporting ranges. Optional
`time_domain: session` distinguishes whole-session event export evidence; other
findings use project time. Source coordinates are upright original normalized
ROIs; blur coordinates are output-frame normalized rectangles.

Migration **0018** adds `privacy_reviews`, cascading with its project. It stores
creator spoiler configuration, a review token, hashed finding IDs/choices and the
checklist bit. It **does not store copied finding text**. Findings are reconstructed
on request. The token hashes the detector version, saved document/revision,
configuration and supporting evidence/metadata. A saved change, re-analysis,
transcript change or configuration change invalidates the prior choices. Config
and decisions are local to the library, not silently restored from a portable
project or another library.

Gate states are: unreviewed/stale; current but unresolved or checklist unchecked;
and current with all decisions resolved and checklist acknowledged. Only the last
state exports. `privacy.review_required` refuses others with HTTP 409. A stale
write gets `privacy.stale_review`; duplicate, unknown or incomplete choices are
refused. No default dismissal or automatic acknowledgment is applied.

The gate covers M24 render submission **and job execution**, M27's seven project
formats, the legacy portable endpoint, and caption-panel sidecar saves. The old
ungated `caption_export` host command is removed; sidecars use `project_export`.
Reads for open exports and review use the same database snapshot. Render execution
rechecks the saved revision and current evidence before encoding.

A text-free `privacy_review` summary records token, version, acknowledgment,
unresolved count and each finding's ID/category/decision in the render plan,
render manifest and `ExportResult`. Project JSON and JSONL headers also carry it
under `extensions`. Plain caption/CSV/FCPXML formats do not embed the summary;
the API envelope carries it. Existing completed manifests remain frozen and
re-exportable; older ones have no review summary. Review cannot retroactively
certify those files or apply effects in third-party editors.

| Route | Action |
|---|---|
| `GET /v1/projects/{id}/privacy-review` | compute findings and gate state |
| `PUT /v1/projects/{id}/privacy-review` | replace `{labels, ranges}` and invalidate decisions |
| `POST /v1/projects/{id}/privacy-review` | `{token, decisions: [{id,state}], acknowledged}` |
| `DELETE /v1/projects/{id}/privacy-review` | delete saved decisions and spoiler config |
| `DELETE /v1/projects/{id}/privacy-text` | explicit text purge described below |

Limits: 50 labels of 100 characters, 100 spoiler ranges, 2,000 findings. Excessive
findings refuse review rather than silently omit risks; shorten the project.

## Moving blur behavior

`Project.overlays[kind=blur]` gains optional `keyframes: [{at_ms, region}]`.
`region` must equal the first key at time zero. Keys increase strictly inside the
blur duration, at most 100, with fixed width/height. Positions interpolate
**linearly**, hold after the last key, and apply on `[start_ms,end_ms)`.

Geometry is shared by TypeScript preview and Python compiler: width/height round
half-up to even output pixels (minimum 8), X/Y floor to even pixels, and positions
shift inside the frame. An epsilon handles floating point at exact pixel edges.
FFmpeg evaluates dynamic crop/overlay expressions after layout/concatenation,
using only validated numeric literals and fixed filter names. Existing static
blurs remain readable and are never omitted. Render engine version is **1.2.0**.

Preview uses the existing video player and an output-sized canvas; it adds no
independent decoder/audio clock. Canvas and FFmpeg blur kernels/color spaces differ,
so appearance is approximate; the shared goldens establish geometry, not identical
pixels or guaranteed anonymization. Compare the actual render before publishing.
Protected HUD warnings conservatively include each moving blur's swept envelope.

Trim, split and reorder rebase moving blurs onto retained source content, including
interpolated start/end keys. A final sample at the last retained millisecond keeps
the trajectory. Undo restores the complete previous document. Exceeding the key
limit fails validation rather than dropping protection. Output-space regions apply
to every aspect ratio; inspect horizontal and vertical output independently.

## Retention and deletion

**Delete review decisions and spoiler configuration** removes that project's row,
invalidates export review and preserves source evidence and edits.

The separate confirmed **Delete derived text** action removes:

- this session's transcript segments and transcript cache rows;
- its current OCR/transcript-text events, historical text observations/decisions,
  and detector cache keys, preventing deleted cached text from being reused;
- this project's captions, text overlays and autosave recovery copy;
- this project's review configuration/decisions.

FTS maintenance triggers remove deleted canonical text in the same transaction.
SQLite secure-delete and a WAL checkpoint are requested. Analysis/transcription
jobs for the session must finish or be cancelled first; otherwise deletion is
refused. The editor reloads afterward to discard its undo history and query cache.
Source footage, managed media, playback copies and models are never deleted.

Other projects may contain explicit copied text. Previously saved exports, library
backups, operating-system snapshots and externally copied files remain under user
control and must be removed separately. This is not a physical secure-erasure claim.
Re-running analysis/transcription can create text again.

## Validation

- Shared valid/invalid TS/Python fixtures: findings, decisions, gate state, source
  ranges and moving-keyframe boundaries.
- `tests/privacy/`: formatted phone/username fixtures; scores, dates, coordinates
  and HUD-number false positives; subtitles, mission/user spoilers, transcript and
  mixed-audio findings; repeated-cut/source mapping; persistence, reversible ignore,
  every export gate, stale/incomplete requests, auth and text/source retention.
- `fixtures/synthetic/privacy-blur-v1.json`: independent horizontal/vertical geometry
  goldens consumed in TypeScript and Python.
- `tests/media/test_privacy_blur.py`: actual FFmpeg moving regions, blur strength,
  restored detail outside/after the range, both aspect ratios, manifests and source
  SHA/mtime preservation. Existing cancellation/failure tests cover the same engine.
- `PrivacyPanel.test.tsx`, `privacyBlur.test.ts`, editor/sidecar tests and native
  allowlist tests cover seeking, choices, undo/retiming, manual controls and refusals.
- `tests/editor_browser.py --captions` supplies temporary synthetic media and the
  real worker for the Chromium walkthrough; transcription uses the documented M18
  test double, not real recognition.
