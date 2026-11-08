## Milestone handoff

- Milestone: M26 — Search and collections
- Outcome: Clips, sessions, detected events (effective labels and OCR text),
  transcript spans and projects are searchable locally with SQLite FTS5.
  - Every result names its source and exact supporting time range and opens the
    session or clip at that moment.
  - The Search screen is keyboard-complete: `/` or Ctrl/Cmd+K, type, ↓, Enter.
  - Filters cover kind, session, source, event label, review state, confidence, date
    and duration, with facet counts.
  - Manual collections hold hand-picked items; rule collections are saved searches
    whose items explain why they matched.
  - The derived index is kept current by triggers in the same transaction as
    canonical changes, can be rebuilt (cancellable job with progress), detects and
    recovers stale or corrupt state, and can be cleared for privacy.
- Files and modules changed:
  - **Worker:** `search/query.py` (safe grammar), `search/filters.py` (filters and
    rule model, SQL compilation, explanations), `search/index.py` (status, rebuild,
    repair, clear), `search/service.py` (search, ranking, facets, snippets,
    collections), `search/benchmark.py` (synthetic library and timings); the `index`
    job handler; search, index and collection API routes; `col` ID prefix; migration
    `0016_search_and_collections.sql` and data fixture `data_v0016.sql`.
  - **Contracts:** 1.20 `search`, `search-index` and `collection` schemas,
    `CollectionId`, generated TS/Pydantic, cross-field rules in both SDKs,
    valid/invalid fixtures, version tests.
  - **Desktop:** `SearchView.tsx`, `SearchResult.tsx`, `CollectionsPanel.tsx`, the
    Search nav link and global shortcut, `@<ms>` session/asset routes that seek on
    open, API client, job label and search invalidation, styles; the host allowlist
    in `media.rs`.
  - **Docs:** [search and collections](../architecture/search.md), storage, desktop
    UI, architecture index, contracts changelog/versioning, README and ledger.
  - **Tests:** `tests/search/` (query, search, index, collections, API, scale),
    `SearchView.test.tsx`, the keyboard search-to-playback E2E in
    `SessionView.test.tsx`, the App keyboard walkthrough and Rust allowlist cases.
- Public contracts or migrations:
  - **Contracts 1.20**, additive: `search` (`SearchResults`, `SearchResult`,
    `SearchRequest`, `SearchFilters`), `search-index` (`SearchIndexStatus`),
    `collection` (`Collection`, `CollectionRule` grammar version 1,
    `CollectionSummary`, create/update/item-ref bodies).
  - **Migration 0016:** `search_documents`, `search_fts` (external-content FTS5,
    `unicode61 remove_diacritics 2`, secure-delete), `search_index_state`,
    `search_source_*` views and maintenance triggers; initial build for existing
    libraries. `collections`/`collection_items` are reshaped (TEXT `col_` IDs,
    `manual`/`rule`, clip and transcript items). Existing rows are kept as manual
    collections with IDs `col_` + zero-padded number. Needs SQLite 3.42+.
  - **API:**
    - `POST /v1/search`
    - `GET /v1/search/index[?check=true]`
    - `POST /v1/search/index/rebuild` (job kind `index`, state `indexing`)
    - `DELETE /v1/search/index`
    - `GET/POST /v1/collections`
    - `GET/PUT/DELETE /v1/collections/{id}`
    - `POST /v1/collections/{id}/items`
    - `DELETE /v1/collections/{id}/items/{n}`
- Commands run:
  - `pnpm contracts:generate`, `pnpm format`.
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - Worker `mypy --platform darwin|win32|linux`.
  - `pnpm build`.
  - `uv run python -m openworld_moments.search.benchmark --clips 10000 --repeats 30`.
  - `OWM_SEARCH_BENCH=1 uv run pytest tests/search/test_benchmark.py`.
- Test and validation results:
  - **Full gate** (`OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`): formatting,
    ESLint/Clippy/Ruff, REUSE, TypeScript and mypy, all tests, and the contract drift
    check pass.
    - Worker: **1027 passed, 1 skipped** (the existing Windows-only junction case on
      macOS).
    - Python contracts **298**, TypeScript contracts **322**, desktop **220**, Rust
      **48**.
    - Two M11 session tests that inserted collections in the old 0001 shape were
      updated to the 0016 shape.
  - **Other checks:** mypy passes for darwin, win32 and linux, and the production
    macOS arm64 build passes.
  - **Worker search tests** (`tests/search/`, 45):
    - query grammar: phrases, prefixes, exclusions, operators as text, Unicode,
      separators, limits and refusals;
    - exact result ranges and IDs for every kind; review decisions changing the
      indexed label, interval and state;
    - ranking: title weight, review factor, confidence ties; every filter field and
      their combination; invalid filters;
    - Unicode, diacritics and CJK; phrase/prefix/exclusion; special-character and
      empty queries; text-only snippets; facets and paging;
    - deletion visible to other connections only after commit (direct SQL and the
      transcript service); rolled-back writes never indexed; session and clip
      changes;
    - rebuild leaves every canonical table byte-identical, with monotonic progress;
      stale detection by counts and by full check; version change; corrupt and
      dropped FTS recovery with secure-delete restored; cancelled rebuild stays
      searchable and marked incomplete; clear removes derived text only and
      re-indexes later changes; upgrade from 0015 builds the index and keeps old
      collections;
    - rule reasons, rule validation, manual lifecycle with cascade on source
      deletion, name and kind checks, collected sessions as attached data;
    - HTTP routes including a real `index` job; 2,000-clip scale and correctness.
  - **10,000-clip acceptance** (`OWM_SEARCH_BENCH=1`): passes the 300 ms budget.
  - **Benchmark** (Apple M4, macOS 26.6.2, Python 3.12.14, SQLite 3.53.4; 90,100
    documents built through the triggers in 23.1 s): ten common queries at 30
    repetitions, p95 25.4–138.4 ms, median 20.3–88.7 ms. Table in
    [search](../architecture/search.md#performance).
  - **Desktop:** results with time ranges and safe snippets, facet/confidence/date/
    duration filters, arrow-key movement, refused queries and ignored characters,
    rebuild/check/two-step clear, add-to-collection and save-as-rule with reasons,
    links for every kind. The keyboard-only E2E goes from Sessions to Search with `/`,
    types a query, ↓, Enter, and lands in the session player at the result's
    unique-session time (Part 2 at 0:01.60 after a 600 ms overlap), then
    Ctrl/Cmd+K returns to Search.
- Decisions made:
  - **One definition per document kind.** SQL views define the documents; triggers,
    rebuild and the full stale check all use them, so they cannot drift.
  - **Transactional triggers instead of a background indexer**, so deletions leave
    results exactly at commit. Upserts plus a text-change guard on the FTS trigger
    avoid full-text churn when only numbers change.
  - **No FTS prefix indexes.** The build is about 2.7× faster (61 s to 23 s at
    10,000 clips) with no measurable cost to prefix queries.
  - **Safe grammar.** Every user item is re-emitted as a quoted FTS5 string; there
    are no raw operators, column filters or NEAR.
  - **Single-pass ranking and facets.** One compact pass over the matches in Python,
    then page rows and snippets only for the page.
  - **Ranking** is BM25 (title ×3) scaled by review state (confirmed/corrected
    ×1.25, rejected ×0.5) and confidence (`0.75 + 0.25 × c`).
  - **Rules** are the search language plus `SearchFilters`, evaluated live; reasons
    quote each item's own values. Manual items cascade with their sources.
  - **Rebuild** runs in short batch transactions; cancellation leaves a valid index
    marked `rebuilding`. A corrupt FTS index is rebuilt from documents, or recreated
    if SQLite cannot repair it.
  - **Privacy:** FTS5 secure-delete always on. Clear deletes every document with
    `secure_delete`, optimizes the empty index and truncates the WAL.
  - **Out of scope:** cloud search, embeddings, web discovery and shared libraries.
- Known limitations:
  - Event and transcript dates use the session start, not the exact moment.
  - Stale events (layout changed since analysis) open at their recorded interval.
  - Captions, project timelines and free-form notes are not indexed beyond project
    titles.
  - A CJK word inside a longer CJK run is found only by prefix (unicode61).
  - Rule collections reflect the index, so they can be incomplete until a rebuild.
  - Collection rename and rule editing exist in the API (`PUT`); the desktop offers
    create, open, add, remove and delete.
  - The 10,000-clip timing is measured on Apple M4 only; CI runs a 2,000-clip guard.
  - **Still outstanding from earlier milestones:** M10's real-phone Windows smoke
    test, unvalidated GTA profiles and unmeasured real whisper.cpp recognition.
- Follow-up milestones affected:
  - **M27** (open exports) can export collections and search manifests.
  - **M28** (privacy review) can use the search index to find text needing review.
  - **M29** (Windows packaging) must bundle SQLite 3.42+ with FTS5.
  - **M31** (accessibility) should include the Search screen and shortcut in
    onboarding.
- Pull request: [#32](https://github.com/heetdalsania/openworld-moments/pull/32)
- Screenshots, reports, or artifacts:
  - [Search and collections](../architecture/search.md) (document contract,
    grammar, ranking, rules, rebuild, privacy and benchmark table).
  - No secrets, user libraries, private paths, footage, generated media, models,
    databases or build outputs are included.
