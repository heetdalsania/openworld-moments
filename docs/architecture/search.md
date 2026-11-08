# Search and collections (M26)

Clips, sessions, detected events, transcript spans and projects are searchable from
the **Search** screen (`/` or Ctrl/Cmd+K anywhere). Every result names its source
and the exact supporting time range, and opens the session or clip at that moment.
Collections keep hand-picked lists or saved searches (rules). Everything runs on
SQLite FTS5 inside the library database: no cloud search, embeddings, web
discovery or shared libraries.

## Searchable documents (index version 1)

`search_documents` (migration 0016) holds one normalized row per searchable item.
It is **derived data**: each kind is defined by one SQL view over the canonical
tables, and the same views feed the triggers, the full rebuild and the stale check.

| Kind | View | Title column | Body column | Range | Other fields |
|---|---|---|---|---|---|
| `clip` | `search_source_clips` | original file name | — | clip time `0..duration` (+ source range) | capture date, duration, source, first session |
| `session` | `search_source_sessions` | session title | — | unique session time `0..duration` | start date, unique duration (overlaps hidden), first clip's source, review state |
| `event` | `search_source_events` | **effective** label | OCR `text`, `speaker`, `category` attributes | **effective** unique-session interval | session date, duration, clip source, label, original confidence, **effective** review state |
| `transcript` | `search_source_transcripts` | speaker | spoken text | unique session time (+ source range in the clip) | session date, duration, clip source, recognition confidence |
| `project` | `search_source_projects` | project title | — | none (opens the editor) | creation date |

"Effective" means the latest M19 review decision overrides the detector's label,
interval and review state; confidence stays the original observation's. Detector
attributes and evidence are read only when their JSON is valid, so an index row can
never make a canonical write fail. The characters U+0002 and U+0003 are reserved as
snippet markers and replaced in indexed text.

User-authored text that is indexed: session titles, project titles, manual event
labels and review corrections. Caption cue text and free-form notes are not indexed
in this version.

The contract for results is `SearchResult` in `search.schema.json` (contracts 1.20):
`key` (`<kind>:<id>`), `kind`, `title` and `snippet` as `{text, match}` segments,
`matched_in`, the IDs, `range` (`timebase` `session` or `clip`), optional
`source_range`, date, duration, source, label, confidence and review state.
Cross-field rules in both SDKs check that keys match their kind and ID, ranges are
ordered, only clip results use clip time, pages fit their totals and facet counts
never exceed the total.

## Keeping the index current

Triggers on `media_assets`, `sessions`, `session_assets`, `events`,
`event_decisions`, `transcript_segments` and `stories` upsert the affected
documents from the views or delete them, **in the same transaction** as the
canonical change. A deleted transcript, event, clip or session therefore leaves the
results exactly when its transaction commits; a rolled-back change never appears.

`search_fts` is an external-content FTS5 table over `title` and `body`
(`unicode61 remove_diacritics 2`, `secure-delete` on). Its triggers only run when
the title or body text actually changes, so numeric refreshes (a clip joining a
session, a review decision that keeps the label) do not touch the full-text index.

## Query language

User text never reaches FTS5 as syntax. The parser
(`openworld_moments/search/query.py`) re-emits every item as a quoted string:

```text
query    := item*                       implicit AND
item     := ["-"] (phrase | word)       "-" excludes (needs one positive item)
phrase   := '"' text '"' ["*"]          an unclosed quote runs to the end
word     := non-space-text ["*"]        "*" = prefix, at least 2 letters first
```

- Words split into letters and digits like the tokenizer (`wanted_level` and
  `wanted-level` both match `wanted level`). Case and diacritics are folded by FTS5
  itself (`café` = `CAFE`).
- `OR`, `NOT`, `NEAR(…)`, `column:` and parentheses are just words.
- Items without a letter or digit (`!!!`, `""`) are ignored and listed in
  `query.ignored`.
- Refused with a 422 and a reason: more than 256 characters, control characters,
  more than 12 items, a prefix shorter than 2 letters, or only exclusions.
- CJK text is one token per run of characters (unicode61); search the whole run or
  a prefix (`クリ*`).

An empty query is a filter-only browse.

## Filters

`SearchFilters` is closed and compiles to fixed SQL with bound parameters. Lists
match any value; fields combine with AND.

| Field | Matches |
|---|---|
| `kinds` | clip, session, event, transcript, project |
| `session_ids` | up to 50 sessions |
| `source_kinds` | xbox, playstation, obs, capture_card, phone_upload, other |
| `event_types` | effective event labels |
| `review_states` | unreviewed, confirmed, corrected, rejected (events and sessions) |
| `min_confidence` | documents that have a confidence (events, transcript spans) |
| `occurred_from` / `occurred_to` | the document's date (clip capture time, otherwise the session start) |
| `min_duration_ms` / `max_duration_ms` | documents with a duration |

## Ranking

With words, results are ordered by

```text
score = bm25(title weight 3, body weight 1)
        × review factor   (confirmed/corrected 1.25, unreviewed or none 1.0, rejected 0.5)
        × confidence factor (0.75 + 0.25 × confidence, or 1.0 without confidence)
```

ascending (BM25 is negative; lower is better), then by document key for stable
pages. Without words: newest date first, then kind and key. Facets (kind, label,
review state, source; top 20 each) count the whole filtered result set. Matched
words in titles and snippets are returned as segments and rendered as text with
`<mark>`, never as HTML.

## Collections

Migration 0016 reshapes the unused 0001 tables. Existing rows become manual
collections with stable IDs (`col_` + the old number, zero-padded).

- **Manual**: items reference exactly one clip, session, event, transcript span or
  project (`ON DELETE CASCADE`). Deleting the source removes the item; re-analysis
  that replaces an event or re-transcription that replaces spans removes their items
  too (review history stays in M19 snapshots). Collected sessions count as attached
  data for session regrouping guards. At most 5,000 items per collection and 500
  collections.
- **Rule-based**: a saved search, evaluated live against the index. No items are
  stored. Each item lists why it matched, one reason per criterion with the item's
  own value, for example `Confidence 0.92 is at least 0.80` or
  `Matches wanted in the label and on-screen text, without bike`.

Rule grammar, version 1 (`CollectionRule` in `collection.schema.json`):

```json
{
  "version": 1,
  "query": "wanted -bike",
  "filters": { "kinds": ["event"], "review_states": ["confirmed", "corrected"], "min_confidence": 0.8 }
}
```

`query` uses the query language above and `filters` is `SearchFilters`. A rule needs
words or at least one filter. Rules are stored canonically and shown in the UI as
plain sentences.

## API

| Route | Purpose |
|---|---|
| `POST /v1/search` | `SearchRequest` → `SearchResults` |
| `GET /v1/search/index[?check=true]` | `SearchIndexStatus`; `check` compares every document with its view and runs the FTS integrity check |
| `POST /v1/search/index/rebuild` | `index` job (state `indexing`), cancellable from Background jobs |
| `DELETE /v1/search/index` | delete all derived search text (refused while a rebuild runs) |
| `GET/POST /v1/collections` | list / create (`CollectionCreate`) |
| `GET/PUT/DELETE /v1/collections/{col_…}` | page with items (`offset`, `limit`) / rename or change rule / delete |
| `POST /v1/collections/{col_…}/items` | add `{kind, id}` (200 if already present) |
| `DELETE /v1/collections/{col_…}/items/{n}` | remove one item |

The desktop host allowlists exactly these routes; IDs, item numbers and the single
`check=true` query are validated before a request reaches the worker.

## Stale and corrupt indexes, rebuild

`search_index_state` records the index version, `current`/`rebuilding`/`cleared`
and the last build time. Status reasons:

| Reason | Detected by |
|---|---|
| `version_changed` | stored index version differs from the code's `INDEX_VERSION` |
| `rebuild_incomplete` | a rebuild was cancelled or interrupted |
| `cleared` | the index was cleared for privacy |
| `documents_out_of_date` | per-kind document counts differ from canonical counts (light check), or any row differs from its view (full check) |
| `full_text_corrupt` | FTS5 `integrity-check` fails (full check), or a search hits a damaged index (503 `search.index_unavailable`) |

The rebuild (`index` job) never writes canonical tables or touches media:

1. Mark the index `rebuilding`. If the full-text index fails its integrity check,
   rebuild it from the stored documents, recreating the FTS table (with
   secure-delete) if SQLite cannot repair it.
2. Per kind, upsert documents from the view in batches of 500 canonical IDs, each
   batch in its own short transaction, checking for cancellation between batches.
3. Delete documents whose source row is gone or whose index version is old.
4. Rebuild and optimize the full-text index, verify it and mark the index current.

A cancelled rebuild leaves a valid, searchable index marked `rebuilding` until the
next complete rebuild. Tests hash every canonical table before and after rebuilds,
recovery and clearing.

## Privacy

- Search, the index and collections are local. There is no telemetry.
- Deleting a transcript or event removes its document in the same transaction;
  FTS5 secure-delete removes the text from the index structures rather than marking
  it deleted.
- **Clear index** deletes every document with `secure_delete` on, rebuilds and
  optimizes the empty full-text index, and truncates the write-ahead log. Clips,
  events, transcripts and collections are untouched. Later changes are indexed again
  by the triggers; the index stays marked `cleared` until rebuilt.
- Snippets, OCR text and transcripts are rendered as text only.

## Performance

`uv run python -m openworld_moments.search.benchmark --clips 10000` builds a
deterministic synthetic library and times ten common queries (words, phrase,
prefix, exclusion, filter-only and date-filtered) through `SearchService`, including
connection, matching, facets and snippets, 30 repetitions each.

Reference machine: Apple M4, macOS 26.6.2 arm64, Python 3.12, SQLite 3.53.4.
Library: 10,000 clips, 1,000 sessions, 30,000 events (half reviewed), 50,000
transcript spans, 100 projects (90,100 documents), built through the triggers in
23.1 s.

| Query | Hits | Median | p95 |
|---|---:|---:|---:|
| `wanted` | 9,475 | 57.1 ms | 67.3 ms |
| `heist` | 10,075 | 53.8 ms | 59.3 ms |
| `police chase` | 5,120 | 43.5 ms | 58.7 ms |
| `"no way"` | 5,134 | 35.9 ms | 49.6 ms |
| `mission comp*` | 10,829 | 88.7 ms | 138.4 ms |
| `crash -bike` | 10,184 | 61.8 ms | 85.4 ms |
| `busted` + events, confidence ≥ 0.8 | 2,685 | 34.1 ms | 42.4 ms |
| events confirmed (no words) | 7,500 | 47.9 ms | 66.6 ms |
| vehicle crash label + Xbox (no words) | 809 | 20.3 ms | 25.4 ms |
| `airport` + March–June dates | 1,763 | 22.6 ms | 26.6 ms |

Every common query is under the 300 ms target (worst p95 138 ms). The test suite
runs the same queries on 2,000 clips with a loose guard; `OWM_SEARCH_BENCH=1` runs
the 10,000-clip acceptance check with the 300 ms budget.

Design choices behind these numbers: one pass over the compact match rows computes
the total, facets and page order, and only the page's rows are fetched with
snippets. No FTS prefix indexes are kept, which made the trigger-built index about
2.7× faster to build with no measurable cost to prefix queries at this size.

## Limits

- Event and transcript dates are the session's start time, not the exact moment.
- An event's search range is its effective unique-session interval. A stale event
  (session layout changed since analysis) still opens at that interval; the session
  screen shows its review status.
- Captions and project timelines are not indexed beyond project titles.
- Rule collections evaluate against the index, so an incomplete index can omit
  items until it is rebuilt.
- A CJK word inside a longer run of CJK characters is found only by prefix.
