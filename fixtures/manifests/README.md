# Fixture manifests

See [fixture policy](../README.md).

- [wanted-v1.json](./wanted-v1.json): versioned M16 synthetic indicator geometry,
  levels, timing, brightness, scale, compression and negative-case recipes.
  Generate using the media-worker fixture helpers/tests; no game media is bundled.
  This synthetic case table is not a gameplay precision/recall dataset.
- [text-v1.json](./text-v1.json): M17 original phrases, explicit Hershey rendering,
  scale/compression/contrast/outline/multiline cases, expected temporal intervals
  and negative/failure coverage. No gameplay or model files are bundled.

- [evaluation-holdout-v1.json](./evaluation-holdout-v1.json): M19 independent temporal annotations by media hash, with [frozen observations and reports](../../docs/evaluation/README.md). Generated media and the private file map stay local.

M20 [story-golden-v1.json](./story-golden-v1.json) contains ten independent synthetic metadata timelines and declared expected windows/coverage; no media or transcript text. See [coverage report](../../docs/stories/sample/report.md).
