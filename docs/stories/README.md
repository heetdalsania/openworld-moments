# Local story generation

M20 exposes the story engine through the authenticated worker API and local CLI.
It proposes drafts from reviewed events or high-confidence detector observations.
No detector, model, media process, account, upload or publishing step runs here.
Story cards and editing controls arrive with the downstream editor milestones.

## Generate and inspect

```bash
uv run --locked --directory services/media-worker owm story ses_YOUR_SESSION_ID \
  --library /absolute/local-library --preset short
```

Choose `moment`, `short`, `extended_short` or `highlight`. `--reviewed-only`
disables unreviewed detector seeds; `--avoid-spoilers` enables the explicit spoiler
penalty. `--pre-roll-ms`, `--post-roll-ms`, `--merge-gap-ms` override roll/gap
preferences within their documented limits. `--force` recomputes without changing
review decisions or saved projects.

Use `--list` for a read without generation, `--history` to include rejected/stale
candidates, and `--offset` for subsequent pages of 50. List custom generations with
the same preset/roll/policy settings. The JSON includes exact source-event
revisions/ranges, beats, alternatives, score components, coverage and warnings.
Review the visible footage and underlying evidence before accepting a suggestion.
GTA/gameplay compatibility remains unvalidated.

## Explicit candidate decisions

Take the candidate's ID and `input_key` and the item's `revision` from the returned
page; do not substitute the page's current input key for a historical candidate.

```bash
uv run --locked --directory services/media-worker owm story-review ses_YOUR_SESSION_ID prj_YOUR_CANDIDATE_ID \
  --library /absolute/local-library --state accepted \
  --input-key CANDIDATE_SHA256 --expected-revision 0
```

Only acceptance creates a Project/Story, ready for M21/M22. No render begins.
Use `--state rejected` to hide a candidate; `--state suggested` restores it.
Each change requires the latest revision, and rejected history stays in SQLite.
Old evidence cannot be accepted; generate fresh suggestions after an edit or
reanalysis. Already edited projects must be managed in the editor rather than
through candidate decisions. Independent manual projects remain untouched even
when a session yields zero automatic candidates.

## Reproduce the synthetic coverage report

```bash
uv run --locked --directory services/media-worker owm story-golden \
  --output /absolute/new-story-report
```

The public [golden timelines](../../fixtures/manifests/story-golden-v1.json)
contain metadata only. They exercise isolated payoff, chase, overlapping events,
missing payoff, long silence, duration pressure, sentence completion, no events,
audio-only input and duplicate removal. The [Markdown report](./sample/report.md)
and [JSON report](./sample/report.json) report setup/payoff coverage, speech
truncation, duplicate time, score components and declared expected windows.
The generated outputs are byte-deterministic; the committed JSON is additionally
indented by the repository formatter. No media, transcript strings or private
paths are included. This is synthetic algorithm coverage, not gameplay quality.
Human median boundary adjustment is explicitly unmeasured.

See [algorithm stages, presets, scoring, reconciliation and limits](../architecture/stories.md).
