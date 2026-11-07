# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic-only example: a sustained bright region, not a gameplay detector."""

from collections.abc import Iterable
from types import MappingProxyType

from openworld_moments.detectors.sdk import AnalysisContext, Detection


class BrightRegion:
    id = "synthetic-bright-region"
    version = "1.0.0"
    capabilities = frozenset({"frames.gray"})
    required_regions = frozenset({"signal"})

    def setup(self, context: AnalysisContext) -> None:
        pass

    def close(self) -> None:
        pass

    def detect(self, context: AnalysisContext) -> Iterable[Detection]:
        region = context.regions["signal"]
        confirmation = int(context.settings.get("confirmation_frames", 3))
        run: list[int] = []

        def finish() -> Detection | None:
            if len(run) < confirmation:
                return None
            return Detection(
                "synthetic.bright_region",
                run[0],
                min(context.duration_ms, run[-1] + 500),
                0.95,
                (
                    MappingProxyType({"kind": "color_rule", "region": region, "score": 0.95}),
                    MappingProxyType(
                        {"kind": "temporal_consistency", "frames": len(run), "score": 1.0}
                    ),
                ),
                MappingProxyType({"synthetic": True}),
            )

        for index, frame in enumerate(context.frames):
            context.check_cancelled()
            x, y, w, h = region
            left, top = int(x * frame.width), int(y * frame.height)
            right = max(left + 1, min(frame.width, int((x + w) * frame.width)))
            bottom = max(top + 1, min(frame.height, int((y + h) * frame.height)))
            samples = b"".join(
                frame.pixels[row * frame.width + left : row * frame.width + right]
                for row in range(top, bottom)
            )
            if samples and sum(samples) / len(samples) >= 200:
                run.append(frame.source_ms)
            else:
                event = finish()
                if event is not None:
                    yield event
                run.clear()
            context.progress(index + 1, max(1, len(context.frames)))
        event = finish()
        if event is not None:
            yield event
