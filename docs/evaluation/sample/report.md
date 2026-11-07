# Local detector evaluation

Dataset: `synthetic-temporal-holdout-v1` (holdout, synthetic).
Profile: `generic-open-world` 1.0.0.
Boundary tolerance: 0 ms, inclusive at both ends.

| Metric | Value |
|---|---:|
| duration_ms | 19000 |
| f1 | 1 |
| false_negatives | 0 |
| false_positives | 0 |
| false_positives_per_hour | 0 |
| median_timestamp_error_ms | 0 |
| precision | 1 |
| processing_ms | 3085.946084 |
| realtime_factor | 6.156945 |
| recall | 1 |
| true_positives | 3 |

## Compatibility matrix

| Resolution | Locale | HUD scale | Compression | Precision | Recall | Footage hours | Status |
|---|---|---:|---|---:|---:|---:|---|
| 320x180 | en | 1 | heavy | 1 | 1 | 0.003056 | synthetic-only |
| 320x180 | en | 1 | light | 1 | 1 | 0.002222 | synthetic-only |

Synthetic results do not establish gameplay compatibility. Local evaluation never automatically validates a profile.
Performance uses frozen recorded analysis time, including proxy preparation/decode; hashes identify the inputs.
Timestamp error is the median of matched mean absolute start/end errors. Matching maximizes pair count, not global timing optimality.
No footage, filenames, paths, OCR text or transcripts are included.

Manifest SHA-256: `d429ef79b0b4720dce161caa199dfc12f587d1bacdc79ffb03edc4f657cace2e`
Observations SHA-256: `91cee424bd96d03093a954f22d65feaf2a2d84558c8658ce645a708d4cb2e23b`
