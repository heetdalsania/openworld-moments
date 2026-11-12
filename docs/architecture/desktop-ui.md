# Desktop library and jobs UI

M09 turns the desktop window into the first usable workflow:

- import media,
- watch background work,
- browse the library,
- play clips,
- understand failures.

Everything runs locally. The UI talks only to the Rust host, which talks to the
worker.

## How the UI reaches the worker

```text
React UI ──invoke("worker_api", {method, path, body})──▶ Rust host ──token──▶ worker /v1/...
React UI ──<video src="owm-media://localhost/asset/<id>/proxy">──▶ Rust host ──▶ file (Range)
Rust host ──worker://job-event, worker://resync, worker://status──▶ React UI
```

- **`worker_api`** (`src-tauri/src/media.rs`, `api_route_allowed`) forwards only
  these routes. Everything else is refused with `request.not_allowed`, including
  shutdown, cleanup, watched-folder reports from the host, and the media lookup.
  The worker token never reaches the web view.

  | Method | Route |
  |---|---|
  | GET | `/v1/assets` (query: `order`, `limit`, `after`, `missing`), `/v1/assets/{id}`, `/v1/assets/{id}/derived`, `/v1/jobs`, `/v1/jobs/{id}`, `/v1/imports/{id}`, `/v1/capabilities`, `/v1/sessions` (query: `limit`, …), `/v1/sessions/{id}`, `/v1/sessions/{id}/overlaps`, `/v1/sessions/{id}/corrections`, `/v1/transcription/models`, `/v1/sessions/{id}/transcript`, `/v1/render/presets`, `/v1/render/encoders`, `/v1/projects/{id}/renders`, `/v1/renders/{job_id}` |
  | POST | `/v1/imports`, `/v1/assets/{id}/derived`, `/v1/assets/check-sources`, `/v1/jobs/{id}/cancel`, `/v1/jobs/{id}/retry`, `/v1/sessions/recompute`, `/v1/sessions/align`, `/v1/sessions/merge`, `/v1/sessions/{id}/split`, `/v1/sessions/{id}/order`, `/v1/sessions/{id}/remove`, `/v1/sessions/{id}/confirm`, `/v1/sessions/{id}/transcribe`, `/v1/projects/{id}/render` (M24; output stays in the library) |
  | PUT | `/v1/sessions/{id}/overlaps/{asset_id}` |
  | DELETE | `/v1/sessions/{id}/transcript` (derived text only, M18) |

  IDs must be well-formed and query strings contain only `[A-Za-z0-9_=&-]`.
  Watched folders keep their own M07 commands.
- **`owm-media://`** is a custom protocol served by the host. URLs name an asset
  and a variant only:
  - `/asset/<id>/original`
  - `/asset/<id>/proxy`
  - `/asset/<id>/waveform`
  - `/asset/<id>/thumbnail/<n>`

  On Windows (WebView2) the same URLs are `http://owm-media.localhost/...`.

  The host asks the worker for the file (`GET /v1/assets/{id}/media/{variant}`,
  host-only). The worker returns a path it has checked:
  - an original only through its import record, with the size still matching;
  - a derived file only when its row is ready and the path is a derived artifact.

  The host then reads the requested byte range. It supports HTTP Range requests
  (one range, up to 4 MiB per response; files up to 16 MiB are sent whole when no
  range is asked) and never writes. The CSP allows this scheme only for
  `img-src`, `media-src`, and `connect-src`.
- **Events:** the host relays job events and asks the UI to resynchronize after
  a reconnect or a sequence gap.

## Routes and components

Routes are hash-based, so reloading the window returns to the same screen.

| Route | Component | Shows |
|---|---|---|
| `#/library` (default) | `LibraryView` | Newest clips first, 60 per page. Thumbnail, name, duration, size, and badges (Original missing, HDR, No audio, Copied to library). Loading, error with retry, and empty states (with Import and a pointer to watched folders) |
| `#/asset/<id>[@<ms>]` | `AssetView` | Player with a playback-copy / original choice, waveform, clickable filmstrip, playback-media status with Rebuild / Try again, file details, and a missing-original notice |
| `#/sessions` | `SessionsView` | Candidate sessions (M11) with played duration, hidden repeated footage, state, and grouping confidence; group, find repeated footage, and merge ([session timeline](./session-timeline.md)) |
| `#/session/<id>[@<ms>]` | `SessionView` | The session as one continuous timeline (M13): two-element player, track with boundaries, thumbnails, waveforms, and hidden-overlap markers, reveal toggle, keyboard controls, and per-clip corrections ([session timeline](./session-timeline.md)); the `TranscriptPanel` (M18) with its privacy notice, engine/model guidance, transcribe/rebuild, two-step delete and timed lines that seek the player ([transcription](./transcription.md)) |
| `#/search` | `SearchView` | Local full-text search (M26): `/` or Ctrl/Cmd+K focuses the box from any screen, arrow keys move between the box and results, Enter opens a result at its moment (`#/session/<id>@<ms>`, `#/asset/<id>@<ms>`); facet filters, confidence/date/duration filters, index status with rebuild, full check and clear, and `CollectionsPanel` for manual lists and rule collections with match reasons ([search](./search.md)) |
| `#/projects` | `ProjectsView` | Paged saved projects and retained unsaved drafts ([focused editor](./focused-editor.md)) |
| `#/project/<id>` | `EditorView` (Export panel includes `OpenExports` and per-render manifest saving, M27) | Source-mapped preview, cut inspector and track, command-only editing, undo/redo, autosave/recovery and read-only event context ([focused editor](./focused-editor.md)) |
| `#/calibration` | `CalibrationView` | Profile defaults, local ROI overrides, frame capture, crop and built-in preview, media-free patch import/export ([calibration](./profile-calibration.md)) |
| `#/settings` | `SettingsView` (in `App.tsx`) | Privacy choices, system check, optional models, Xbox onboarding and watched folders (M07), display and motion, diagnostics, and Help and setup (run setup again, show library folder) (M31) |
| `#/phone` | `PhoneImport` | Import from phone (M10): network choice, security warning, QR code, countdown, per-file status; leaving the screen closes the upload page ([phone upload](./phone-upload.md)) |

The session screen also offers manual range-to-project creation (`CreateProject`).
Project metadata endpoints and save semantics are documented in the
[focused editor](./focused-editor.md) and [model](./editor-projects.md) guides.

Global, in `App.tsx`:

- **Navigation:** Library, Sessions, Projects, and Settings. Other spec 10.1 sections arrive with
  their milestones.
- **Import:** opens `ImportPanel`. Choose files or folders, or drop them onto the
  window, then choose reference (the default, remembered) or managed.
- **Background jobs:** toggles `JobCenter`, with a running count.
- **Worker banner:** starting, restarting (jobs are kept), or failed.
- **Skip to content** link.
- **First-run setup** (M31, `Onboarding`): while `onboarding` is `pending` in the
  preferences, setup replaces the routed screen. Steps: welcome (what the app never
  does), system check, import methods and default mode, privacy choices, display, done.
  Every step can be skipped; choices save as they are made.
- **Announcer** (M31): one polite and one assertive live region. Jobs seen running
  in this session are announced when they finish, are cancelled or fail.

Supporting modules:

| Module | Role |
|---|---|
| `api.ts` | Typed client (contract types) and plain-language error text (`describeError`) |
| `query.ts` | Small shared query cache (`useQuery`, `invalidate`, `useAction`) |
| `jobs.ts` | Durable job store. Loaded from `GET /v1/jobs` at start, after a worker (re)start, and on resync; live events update it. Finished imports refresh the library, finished `proxy` jobs refresh that asset |
| `media.ts` | `owm-media` URLs, waveform parsing (`owm-waveform` v1), durations |
| `route.ts` | Hash router |
| `preferences.ts` | M31 per-user preferences under `owm.preferences.v1`: setup state, privacy consent (`phoneLan`, `modelDownloads`, both off by default), appearance (theme, text size, motion). Malformed data falls back to the safe defaults. `requireConsent` guards `startPhone` and `installModel` |
| `a11y.ts` | M31 `useDialogFocus`: focus in, Tab trap, Escape, focus returned to the opener |
| `timeline.ts` | Source ↔ virtual session time mapping (M13) |
| `player.ts` | `SessionPlayer`: two-element playback across clip boundaries (M13) |

## Behavior worth knowing

- **Playback preparation is automatic.** Opening a clip whose playback copy,
  thumbnails, or waveform are not prepared (or are missing or stale) starts one
  `proxy` job (M08), at most once per visit. **Rebuild playback media** forces
  regeneration; **Try again** retries a failure.
- **Playback choice:**
  - the playback copy plays when it is ready (or stale but playable);
  - otherwise the original plays, with a note when the policy says it may not
    play smoothly;
  - a missing original disables the Original choice, while a playback copy keeps
    playing.
- **Missing original vs. failed copy:**
  - a missing original shows a notice ("missing or offline… Nothing was deleted");
  - a failed copy shows its error ("The playback copy could not be made: …") and
    a Try again button.
- **Jobs stay visible.** The job center is outside the routed view, and its
  state comes from the worker. After navigation, a UI reload, or a worker
  restart, running and finished jobs are still listed.
  - **Cancel and Retry** show the state the worker returns.
  - **Retry** appears only for retryable failures.
  - **Errors** show plain text first. The code and the tool's (path-redacted)
    stderr tail are folded under "Technical details". There are no stack traces.
- **Import results:** an import job lists its counts (imported, already in the
  library, found again, skipped, failed) and the files that were not imported,
  with reasons.
- **Originals:**
  - The UI has no action that deletes, moves, renames, or edits a source.
  - Copy in the import dialog and asset view says so.
  - Tests check that no button suggests it.

## Keyboard and accessibility

- **Keyboard:** every primary control is a native link, button, or form field.
  Tab order:
  1. Skip to content;
  2. Library, Sessions, Projects, and Settings;
  3. Import and Background jobs;
  4. view controls;
  5. clip cards.

  Focus rings are always visible (`:focus-visible`; date fields use `:focus`).
- **Dialogs:** the import dialog is labelled (`role="dialog"`, `aria-modal`),
  moves focus to its first button, keeps Tab inside, closes with Escape and returns
  focus to the control that opened it (M31).
- **Themes (M31):** `data-theme` on the root (`light`, `dark`, `high-contrast`) over
  the system scheme; `prefers-contrast: more` and `forced-colors: active` are
  honored. Token contrast is tested (AA, AAA for high contrast).
- **Text size and motion (M31):** the root font size scales rem-based layout
  (100–200%); `data-motion="reduce"` and `prefers-reduced-motion` disable
  transitions. The top bar wraps, so 200% text, 200% zoom and 400 px windows do not
  scroll sideways.
- **Checks:** `accessibility.test.tsx` runs axe-core on the primary screens and every
  setup step; `scripts/docs/a11y-smoke.py` measures keyboard focus, zoom, narrow
  windows, forced colors and reduced motion in Chrome. See the
  [accessibility guide](../guides/accessibility.md#support-matrix).
- **Labels:** progress bars carry labels and value text. Status changes use
  `role="status"`, errors `role="alert"`. Thumbnails in the filmstrip are buttons
  named "Jump to m:ss", and the waveform has an image label.

## Tests

- **UI** (`apps/desktop/src/*.test.tsx`, Vitest + Testing Library + user-event),
  with a fake host (`src/testing/fakeHost.ts`):
  - **every state** of the library, asset view, job center, and import dialog;
  - **a keyboard-only walkthrough:** tab order, Import opened with Enter, files
    chosen and the import started without a mouse, Escape closing the dialog;
  - **worker restart:** while the UI is open;
  - **reload recovery:** the hash route restores the asset screen;
  - **drag and drop;**
  - **live job events and resync.**
- **End-to-end:** the real worker and FFmpeg, through the host's code. Run:

  ```bash
  cargo test -p openworld-moments-desktop --test library_e2e
  ```

  It covers:
  - **import:** a synthetic MKV through `/v1/imports`;
  - **playback media:** a `proxy` job, as the asset view starts it;
  - **playback:** proxy byte ranges through `owm-media`, the way a `<video>`
    element asks for them, plus the original, a thumbnail, and the waveform;
  - **errors:** they carry no paths;
  - **a moved original:** reported as missing while the proxy still plays;
  - **a worker crash and restart:** jobs and media survive.

  CI installs FFmpeg for this test (`OWM_REQUIRE_FFMPEG=1`). `session_e2e`
  does the same for sessions: group, align, reorder, and override through the
  allow-listed routes ([session timeline](./session-timeline.md#tests)).

## Known player limitations

- **Formats:** the original plays only in formats the system web view decodes.
  That's H.264/AAC MP4 everywhere. HEVC, MKV, and VP9 depend on the platform,
  which is why the proxy policy (M08) exists.
- **Seeking:** in an original depends on its keyframe spacing. Proxies have one
  keyframe per second.
- **Waveform:** shown for orientation; it is not linked to the playhead yet.
- **Thumbnails** seek the player but do not scrub.
- **No playback speed or A/V offset controls.** The editor milestones (M21, M22)
  own those. Frame stepping exists on the session screen (M13), not on a single
  clip's page. Session playback has its own limitations
  ([session timeline](./session-timeline.md#player-limitations)).
- **Bounded responses:** large files are served in 4 MiB ranges. Players that
  request without a Range header get the first 4 MiB of a file larger than
  16 MiB with status 206. Every supported web view sends ranges.

M15 adds the profile calibration routes and two native export commands described
in [Profile calibration](./profile-calibration.md#patch-format-and-api).

## M23 caption and audio panels

`CaptionPanel` and `AudioPanel` extend the project editor. Every change uses M21 commands/undo/autosave. Native `caption_export` opens an explicit exclusive-create SRT/VTT save dialog; it accepts no destination path from the webview. See [captions and audio](./captions-and-audio.md) for fields, shortcuts, preview limits, sidecars and validation.

## M28 privacy review

See [privacy and spoiler review](./privacy-review.md) for the mandatory current-review
gate on project exports and new renders, contracts 1.22, output-space moving blur
keyframes, local hashed decisions and explicit text-only deletion. Caption-panel
sidecars now flush the project and use the gated `project_export` host command;
`caption_export` is removed. Render engine 1.2.0 uses end-exclusive privacy blurs.
Migration 0018 stores review configuration/decisions without copied evidence text.
