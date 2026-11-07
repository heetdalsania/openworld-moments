# Synthetic story coverage

Generator: owm-story 1.0.0.

| Case | Pass | Setup coverage | Payoff coverage | Speech truncations | Duplicate ms |
|---|---|---:|---:|---:|---:|
| isolated-event | True | 1.0 | 1 | 0 | 0 |
| chase-sequence | True | 1.0 | 1 | 0 | 0 |
| overlapping-events | True | 1.0 | 1 | 0 | 0 |
| no-payoff | True | 1.0 | 0 | 0 | 0 |
| long-silence | True | 1.0 | 1 | 0 | 0 |
| duration-pressure | True | 0.0 | 1 | 0 | 0 |
| complete-sentence | True | 1.0 | 1 | 0 | 0 |
| no-events | True | N/A | N/A | 0 | 0 |
| supporting-audio-only | True | N/A | N/A | 0 | 0 |
| duplicate-removal | True | 1.0 | 1 | 0 | 0 |

Setup is measured pre-event context, not a claim of semantic understanding. Payoff requires an explicit supported event. Audio never seeds a story.
No gameplay quality, publishing performance or human boundary-adjustment result is claimed. Median manual boundary adjustment is unmeasured.
