# Render presets

Export presets for the M24 render engine (spec 11.4). Each file is one
`render-preset` contract document (`packages/contracts/schemas/render-preset.schema.json`),
so contributors can add presets without code changes.

| Preset | Output | Video | Audio |
|---|---|---|---|
| `horizontal-1080p30` | 1920×1080, 30 fps | H.264 CRF 20 | AAC 192 kb/s, 48 kHz |
| `horizontal-source-fps` | 1920×1080, the first clip's frame rate | H.264 CRF 20 | AAC 192 kb/s, 48 kHz |
| `horizontal-720p30` | 1280×720, 30 fps | H.264 CRF 23 | AAC 160 kb/s, 48 kHz |

The renderer validates every preset against the contract and refuses unknown fields,
odd dimensions and HEVC (M24 renders H.264 only). Vertical, Discord-size and
HUD-aware presets arrive with M25/M27. See [render engine](../docs/architecture/render.md).
Preset data is licensed under Apache-2.0.

M25 adds [vertical layouts](../docs/architecture/vertical-layouts.md) with `vertical-1080x1920-30` and `vertical-source-fps` presets.
