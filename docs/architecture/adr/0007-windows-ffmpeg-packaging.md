# ADR-0007: Windows FFmpeg packaging policy

- Status: Proposed; maintainer decision required before implementation
- Date: 2026-11-08
- Milestone: M29
- Deciders: project maintainers

## Context

M29 must deliver a Windows 11 x64 package that imports, prepares playback copies
and renders without asking a nontechnical tester to configure a terminal.
The checked baseline is the M28 merge, `6e9410a`.

Specification §15.5 prefers LGPL-compatible FFmpeg and requires deliberate
acceptance before bundling GPL-only codecs. The §20 risk table describes an
LGPL build policy. The merged implementation requires `libx264`:

- M08's `proxy-h264-sdr` v1 recipe selects it in
  `services/media-worker/openworld_moments/derived/recipes.py`.
- `media/tools.py` includes it in `DERIVED_ENCODERS`; an LGPL build without it
  cannot pass the existing derived-media capability gate.
- M24's `render/encoders.py` makes it the CPU encoder and the explicit fallback
  after a hardware failure. Hardware availability cannot replace a CPU fallback.

FFmpeg's [license documentation](https://www.ffmpeg.org/legal.html) identifies
libx264 as GPL and explains that enabling GPL components changes FFmpeg's
license. Its [x264 build documentation](https://www.ffmpeg.org/general.html#x264)
requires the GPL configuration option. Consequently, packaging today's required
encoder while describing that distribution as LGPL would be inaccurate.

`AGENTS.md` requires implementation to stop for a material spec/code conflict,
and `MILESTONES.md` requires the planning correction to merge first. This ADR
records that pause; it does not announce an installer or release.

## Proposed decision

Accept a narrow M29 exception to the LGPL preference: retain the existing
`libx264` proxy recipe and CPU render behavior, and package a GPL-enabled
FFmpeg/FFprobe distribution with its actual license and corresponding source.

The implementation must:

1. Pin immutable runtime and source versions and SHA-256 checksums; do not use a
   moving download as a release dependency. Record FFmpeg's configure output and
   the applicable SPDX license identifiers in the runtime inventory.
2. Include the applicable license texts and third-party notices, and distribute
   matching corresponding source and build instructions alongside package assets.
   Identify bundled external libraries as well as FFmpeg itself. A bare upstream
   homepage is not a substitute for matching source provenance.
3. Reject `--enable-nonfree` builds and components whose redistribution rights or
   matching source cannot be established. Including libx264 does not approve
   unrelated optional codecs or dependencies.
4. Report the actual packaged FFmpeg version and capabilities through the doctor,
   and preserve the CPU fallback. Keep media processes behind argument arrays.
5. Preserve the application's existing AGPL license, contracts/profile licenses,
   source-media safety rules and no-silent-download policy. This decision concerns
   the FFmpeg distribution; it does not relicense the repository.

M29 still owns its runtime/model inventory, notices and package checksums. M30
owns the complete transitive SBOM and security audit, as already planned. This
exception does not waive either milestone's acceptance criteria or constitute
legal clearance for publishing users' media.

## Alternative requiring a broader planning change

Retain a strict LGPL-only FFmpeg distribution and replace the required libx264
proxy/CPU-render path with a qualified alternative. That changes encoder
selection, presets, capability gates, quality mapping, reproducibility and golden
fixtures. It needs a separately approved prerequisite scope before M29, rather
than an unannounced encoder substitution in packaging code.

## Restart and validation gates

The maintainer must accept one of these policies. For the proposed exception,
mark this ADR Accepted, remove the proposal/pause wording from the spec and M29
status, and merge the planning correction before restarting implementation.
Do not mark M29 Complete on that planning merge.

All M29 validation remains mandatory, including clean Windows 11 x64 install,
first launch, import, render, upgrade and uninstall; interrupted/offline/low-disk
downloads, signature/manifest corruption and Unicode paths; and a reproducibility
comparison with any toolchain nondeterminism explained.

Current CI has Windows worker/Rust tests and a desktop `--no-bundle` build. Those
are not evidence of installer or clean-client qualification. This session runs
on macOS; no Windows qualification was performed. Packaging work must arrange
and record that Windows evidence before claiming completion or merging M29 as
fully delivered. M32's later public-alpha gate does not replace M29's VM run.

The M18 model manager is an explicit M29 dependency because M29 extends its
registry, integrity checks and optional whisper.cpp adapter. M18 is already
merged, so recording this dependency does not delay the roadmap.
