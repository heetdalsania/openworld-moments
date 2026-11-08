# Vertical layouts (M25)

M25 adds an independent vertical variant to each cut. Switching the editor preview
between 16:9 and 9:16 keeps one project and leaves every existing `Segment.crop`
unchanged. Horizontal presets continue to use that original field. The two new
JSON presets are `vertical-1080x1920-30` and `vertical-source-fps`; both render
1080×1920 through the M24 renderer and its normal source verification,
progress, cancellation, validation and atomic completion.

## Contract and coordinates

Contracts **1.19**, editor model version **1**, no migration. An optional
`Segment.vertical_crop` has:

- `layout_version: 1`;
- `strategy: fit | fixed | keyed`;
- `background: solid | blur`;
- `keyframes: [{at_ms, region: [x,y,width,height]}]`;
- optional `suggestion`: algorithm, confidence, reason and profile ID/version.

Regions are normalized against the **upright original**, after rotation. Times
are cut-relative milliseconds. Absent settings mean complete-frame fit with a
black background. Fit has no keys. Fixed has exactly one key at zero. Keyed starts
at zero; up to 100 keys must strictly increase inside the cut. Dimensions are
constant across a cut, while positions may vary. All regions stay inside the
source. Both contract runtimes reject invalid dimensions, order, strategy and
bounds. Portable project JSON retains these fields.

Crop widths/heights round down to even original pixels, minimum two pixels;
positions floor to integer original pixels and clamp inside the source. Complete
frame fit retains odd source dimensions too. The foreground scales to fit the
output, rounding down to even pixels, and is centered at integer coordinates.
`render/layout.py` and `verticalLayout.ts` implement the same versioned geometry.
The backing canvas is actually 1080×1920, displayed smaller in the editor. Proxy
pixels are sampled using the quantized original coordinates, so proxy resolution
does not change the crop. Browser/native decoders apply rotation before drawing.

## Interpolation and editing

Between keys, positions interpolate with `q*q*(3-2*q)`, where `q` is the clamped
fraction of elapsed key time. Before the first and after the last key, hold its
position. There is no implicit zoom: widths/heights stay fixed. FFmpeg evaluates
numeric crop expressions per frame, using one input per cut, rather than opening
one input for each moving frame. Numeric expressions go into M24's graph file;
profile names, filenames, captions and paths never enter expressions or a shell.

The panel offers fit, fixed crop, keyed crop, solid/blurred background, reset,
editable key times/rectangles, a draggable center and numeric keyboard controls.
The source map labels retained and removed areas and draws profile-protected
regions. A dashed rectangle shows unapplied fields. Size changes apply to all
keys, clamping other positions within the new size. Fields persist across
unrelated audio/caption commands. Every applied change uses command history,
autosave, undo/redo and normal recovery; resetting fields alone does not save.

Splits and trims reanchor the retained boundary to its interpolated source region;
keyed cuts also retain an end sample. Easing restarts between retained anchors,
so trimming a transition can change its intermediate speed. Reordering carries
keys with the cut. Undo restores exact prior keys. A boundary edit that would
exceed the 100-key limit is refused instead of dropping authored keys.

## Profiles, suggestions and warnings

The explicit project profile uses the M15 **effective calibration**, including
local ROI overrides. Changed bases, calibration conflicts, mismatched versions,
incompatible upright aspect ratios/resolutions and unavailable profiles produce
an unknown-protection warning. Manual editing and export remain possible after
explicit review. Frame compatibility uses the existing 1% aspect-ratio tolerance.
`safe_zones.preserve` references named regions; new optional `subject_hints` names
static regions from the same map. Both are validated against `regions`.

`static-profile/1` proposes **one constant decision per cut** when the user asks
for it. It finds the union of protected regions and subject hints and places the
largest 9:16 source window around that union. If the union cannot fit, or rounding
would remove more than 5% of a protected region, it proposes complete-frame fit.
There is no motion, face or object detector. Rapid-motion footage cannot make this
planner jitter because sampled motion never drives the crop. Confidence is a
heuristic label: **0.65** for a feasible static-profile crop, **0.25** for a
conservative fit fallback. These values are not calibrated success probabilities.
The algorithm, confidence, explanation and profile identity are saved when the
suggestion is explicitly accepted. Manual keyframe changes clear the suggestion
provenance; every suggestion can be replaced or reset.

A protected region is materially removed when less than **95%** remains visible.
Checks include key endpoints and midpoints. The worker also warns when a privacy
blur active during the cut could cover over **5%** of a mapped protected region;
this uses a conservative swept envelope of the moving region across the cut,
including narrow crossings between keys. Render plans retain the effective
profile and exact numeric framing inputs. Before vertical export the UI lists
crop/unknown-profile warnings and requires an explicit review checkbox covering
all cuts and privacy blurs. Editing the document, preset or loaded profile clears
the acknowledgment. The worker independently checks current protected regions
and refuses warnings without `review_layout: true`.

The render request can include `expected_revision`; the desktop supplies the
revision returned after flushing autosave. Preflight and job execution refuse a
changed revision with `render.revision_changed`, rather than using a subsequently
saved project. Layout-review refusal is `render.layout_review_required`.

## Backgrounds and validation

Solid fit uses black bars. Blurred fill enlarges the same retained source region
behind the fitted foreground, then blurs it; the complete foreground stays visible.
Canvas blur approximates FFmpeg's box blur; crop geometry is the parity contract,
not identical blur kernels or color management. M24 text omission and privacy blur
behavior remain in force. Black-frame validation now compares the vertical
foreground against its corresponding source crop, avoiding false failures from
intentional letterboxing while still rejecting black foregrounds over bright
source content.

The shared text-only golden manifest is
`fixtures/synthetic/vertical-layout-v1.json`: landscape fit, portrait fit, rotated
upright geometry, odd resolutions and smoothstep quarter/midpoint crops. Both
runtimes check its independent integer expectations. Real FFmpeg tests measure
fixed and moving white-marker edges against preview geometry within **2 output
pixels**, render both backgrounds, portrait and rotation-metadata sources, verify
source preservation and horizontal settings, and exercise cancellation. Generated
media stays temporary and is never committed.

## Limits and follow-up

Suggestions are static profile framing, not tracked gameplay action. Missing or
conflicting HUD zones often make fit the appropriate choice. Canvas/proxy color,
scaling and blurred backgrounds may differ from original-quality FFmpeg output.
Privacy blurs and unsupported text are not previewed here. Caption burn-in still
requires M24's explicit omission. M24's 120-input and graph/process limits remain.
Native WebView performance and real-game framing quality require later device and
legitimate-footage qualification. M26 is next; M27 owns saving exports outside the
library and broader open manifests. No social publishing or face tracking is added.
