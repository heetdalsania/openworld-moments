-- SPDX-License-Identifier: AGPL-3.0-or-later
-- M26: local full-text search and collections.
--
-- search_documents is derived data: one normalized row per searchable item, built
-- only from canonical tables through the search_source_* views (index version 1).
-- Triggers on the canonical tables replace a document in the same transaction as
-- the change, so a deleted transcript or event leaves the results when it commits.
-- Triggers never write canonical tables; JSON is read only when it is valid, so a
-- canonical write can never fail because of the index. The full-text index is an
-- external-content FTS5 table with secure-delete on, so deleted text is removed
-- from the index rather than only marked deleted.

CREATE TABLE search_index_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    index_version  INTEGER NOT NULL CHECK (index_version >= 1),
    status         TEXT NOT NULL CHECK (status IN ('current', 'rebuilding', 'cleared')),
    built_at       TEXT,
    updated_at     TEXT NOT NULL
);

CREATE TABLE search_documents (
    id               INTEGER PRIMARY KEY,
    doc_key          TEXT NOT NULL UNIQUE,
    kind             TEXT NOT NULL
                         CHECK (kind IN ('clip', 'session', 'event', 'transcript', 'project')),
    session_id       TEXT,
    asset_id         TEXT,
    event_id         TEXT,
    transcript_id    INTEGER,
    project_id       TEXT,
    title            TEXT NOT NULL,
    body             TEXT NOT NULL,
    start_ms         INTEGER,
    end_ms           INTEGER,
    source_start_ms  INTEGER,
    source_end_ms    INTEGER,
    occurred_at      TEXT,
    duration_ms      INTEGER,
    source_kind      TEXT,
    event_type       TEXT,
    confidence       REAL,
    review_state     TEXT,
    index_version    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX search_documents_kind ON search_documents (kind, occurred_at);
CREATE INDEX search_documents_session ON search_documents (session_id);
CREATE INDEX search_documents_asset ON search_documents (asset_id);
CREATE INDEX search_documents_event ON search_documents (event_id);
CREATE INDEX search_documents_transcript ON search_documents (transcript_id);
CREATE INDEX search_documents_project ON search_documents (project_id);
CREATE INDEX search_documents_type ON search_documents (event_type);

CREATE VIRTUAL TABLE search_fts USING fts5(
    title, body,
    content = 'search_documents', content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);
INSERT INTO search_fts (search_fts, rank) VALUES ('secure-delete', 1);

CREATE TRIGGER search_documents_ai AFTER INSERT ON search_documents BEGIN
    INSERT INTO search_fts (rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER search_documents_ad AFTER DELETE ON search_documents BEGIN
    INSERT INTO search_fts (search_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
END;
CREATE TRIGGER search_documents_au AFTER UPDATE OF title, body ON search_documents
WHEN old.title IS NOT new.title OR old.body IS NOT new.body BEGIN
    INSERT INTO search_fts (search_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO search_fts (rowid, title, body) VALUES (new.id, new.title, new.body);
END;

-- Source views (index version 1). Every view returns the same columns. Control
-- characters 0x02/0x03 are reserved as snippet markers and are replaced.

CREATE VIEW search_source_clips AS
SELECT
    'clip:' || a.id AS doc_key,
    'clip' AS kind,
    (SELECT sa.session_id FROM session_assets sa WHERE sa.asset_id = a.id
     ORDER BY sa.session_id LIMIT 1) AS session_id,
    a.id AS asset_id,
    NULL AS event_id,
    NULL AS transcript_id,
    NULL AS project_id,
    replace(replace(a.original_name, char(2), ' '), char(3), ' ') AS title,
    '' AS body,
    0 AS start_ms,
    a.duration_ms AS end_ms,
    0 AS source_start_ms,
    a.duration_ms AS source_end_ms,
    a.captured_at AS occurred_at,
    a.duration_ms AS duration_ms,
    a.source_kind AS source_kind,
    NULL AS event_type,
    NULL AS confidence,
    NULL AS review_state
FROM media_assets a;

CREATE VIEW search_source_sessions AS
SELECT
    'session:' || s.id AS doc_key,
    'session' AS kind,
    s.id AS session_id,
    NULL AS asset_id,
    NULL AS event_id,
    NULL AS transcript_id,
    NULL AS project_id,
    replace(replace(s.title, char(2), ' '), char(3), ' ') AS title,
    '' AS body,
    0 AS start_ms,
    (SELECT coalesce(sum(max(0, a.duration_ms - CASE WHEN sa.order_index =
                (SELECT min(x.order_index) FROM session_assets x WHERE x.session_id = s.id)
            THEN 0 ELSE sa.overlap_with_previous_ms END)), 0)
     FROM session_assets sa JOIN media_assets a ON a.id = sa.asset_id
     WHERE sa.session_id = s.id) AS end_ms,
    NULL AS source_start_ms,
    NULL AS source_end_ms,
    s.started_at AS occurred_at,
    (SELECT coalesce(sum(max(0, a.duration_ms - CASE WHEN sa.order_index =
                (SELECT min(x.order_index) FROM session_assets x WHERE x.session_id = s.id)
            THEN 0 ELSE sa.overlap_with_previous_ms END)), 0)
     FROM session_assets sa JOIN media_assets a ON a.id = sa.asset_id
     WHERE sa.session_id = s.id) AS duration_ms,
    (SELECT a.source_kind FROM session_assets sa JOIN media_assets a ON a.id = sa.asset_id
     WHERE sa.session_id = s.id ORDER BY sa.order_index LIMIT 1) AS source_kind,
    NULL AS event_type,
    NULL AS confidence,
    s.review_state AS review_state
FROM sessions s;

-- Events use the effective view: the latest review decision overrides the label,
-- the interval and the review state. OCR text, speaker and category are body text.
CREATE VIEW search_source_events AS
SELECT
    'event:' || e.id AS doc_key,
    'event' AS kind,
    e.session_id AS session_id,
    e.asset_id AS asset_id,
    e.id AS event_id,
    NULL AS transcript_id,
    NULL AS project_id,
    replace(replace(coalesce(
        CASE WHEN json_valid(d.decision_json) THEN json_extract(d.decision_json, '$.type') END,
        e.type), char(2), ' '), char(3), ' ') AS title,
    replace(replace(trim(
        coalesce(CASE WHEN json_valid(e.attributes_json)
                      THEN json_extract(e.attributes_json, '$.text') END, '') || ' ' ||
        coalesce(CASE WHEN json_valid(e.attributes_json)
                      THEN json_extract(e.attributes_json, '$.speaker') END, '') || ' ' ||
        coalesce(CASE WHEN json_valid(e.attributes_json)
                      THEN json_extract(e.attributes_json, '$.category') END, '')
    ), char(2), ' '), char(3), ' ') AS body,
    coalesce(CASE WHEN json_valid(d.decision_json)
                  THEN json_extract(d.decision_json, '$.start_ms') END, e.start_ms) AS start_ms,
    coalesce(CASE WHEN json_valid(d.decision_json)
                  THEN json_extract(d.decision_json, '$.end_ms') END, e.end_ms) AS end_ms,
    NULL AS source_start_ms,
    NULL AS source_end_ms,
    s.started_at AS occurred_at,
    coalesce(CASE WHEN json_valid(d.decision_json)
                  THEN json_extract(d.decision_json, '$.end_ms') END, e.end_ms)
      - coalesce(CASE WHEN json_valid(d.decision_json)
                      THEN json_extract(d.decision_json, '$.start_ms') END, e.start_ms)
      AS duration_ms,
    a.source_kind AS source_kind,
    coalesce(CASE WHEN json_valid(d.decision_json)
                  THEN json_extract(d.decision_json, '$.type') END, e.type) AS event_type,
    e.confidence AS confidence,
    coalesce(CASE WHEN json_valid(d.decision_json)
                  THEN json_extract(d.decision_json, '$.state') END, e.review_state) AS review_state
FROM events e
JOIN sessions s ON s.id = e.session_id
LEFT JOIN media_assets a ON a.id = e.asset_id
LEFT JOIN event_decisions d ON d.event_id = e.id
    AND d.revision = (SELECT max(x.revision) FROM event_decisions x WHERE x.event_id = e.id);

CREATE VIEW search_source_transcripts AS
SELECT
    'transcript:' || t.id AS doc_key,
    'transcript' AS kind,
    t.session_id AS session_id,
    t.asset_id AS asset_id,
    NULL AS event_id,
    t.id AS transcript_id,
    NULL AS project_id,
    replace(replace(coalesce(t.speaker, ''), char(2), ' '), char(3), ' ') AS title,
    replace(replace(t.text, char(2), ' '), char(3), ' ') AS body,
    t.start_ms AS start_ms,
    t.end_ms AS end_ms,
    t.source_start_ms AS source_start_ms,
    t.source_end_ms AS source_end_ms,
    s.started_at AS occurred_at,
    t.end_ms - t.start_ms AS duration_ms,
    a.source_kind AS source_kind,
    NULL AS event_type,
    t.confidence AS confidence,
    NULL AS review_state
FROM transcript_segments t
JOIN sessions s ON s.id = t.session_id
LEFT JOIN media_assets a ON a.id = t.asset_id;

CREATE VIEW search_source_projects AS
SELECT
    'project:' || p.id AS doc_key,
    'project' AS kind,
    p.session_id AS session_id,
    NULL AS asset_id,
    NULL AS event_id,
    NULL AS transcript_id,
    p.id AS project_id,
    replace(replace(p.title, char(2), ' '), char(3), ' ') AS title,
    '' AS body,
    NULL AS start_ms,
    NULL AS end_ms,
    NULL AS source_start_ms,
    NULL AS source_end_ms,
    p.created_at AS occurred_at,
    NULL AS duration_ms,
    NULL AS source_kind,
    NULL AS event_type,
    NULL AS confidence,
    NULL AS review_state
FROM stories p;

-- Transactional maintenance. Inserts and changes upsert the affected documents from
-- the views (which return nothing once the canonical row is gone); deletions delete
-- them. An upsert that leaves title and body unchanged does not touch the full-text
-- index.

CREATE TRIGGER search_clip_ai AFTER INSERT ON media_assets BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_clips WHERE asset_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_clip_au AFTER UPDATE OF original_name, captured_at, duration_ms, source_kind
ON media_assets BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_clips WHERE asset_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_sessions
    WHERE session_id IN (SELECT session_id FROM session_assets WHERE asset_id = new.id)
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_clip_ad AFTER DELETE ON media_assets BEGIN
    DELETE FROM search_documents WHERE kind = 'clip' AND asset_id = old.id;
END;
CREATE TRIGGER search_session_ai AFTER INSERT ON sessions BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_sessions WHERE session_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_session_au AFTER UPDATE OF title, started_at, review_state ON sessions BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_sessions WHERE session_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
-- Events and transcript spans take their date from the session.
CREATE TRIGGER search_session_date_au AFTER UPDATE OF started_at ON sessions
WHEN old.started_at IS NOT new.started_at BEGIN
    UPDATE search_documents SET occurred_at = new.started_at
    WHERE session_id = new.id AND kind IN ('event', 'transcript');
END;
CREATE TRIGGER search_session_ad AFTER DELETE ON sessions BEGIN
    DELETE FROM search_documents
    WHERE session_id = old.id AND kind IN ('session', 'event', 'transcript');
END;
CREATE TRIGGER search_member_ai AFTER INSERT ON session_assets BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_sessions WHERE session_id = new.session_id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_clips WHERE asset_id = new.asset_id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_member_au AFTER UPDATE ON session_assets BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_sessions WHERE session_id IN (old.session_id, new.session_id)
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_clips WHERE asset_id IN (old.asset_id, new.asset_id)
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_member_ad AFTER DELETE ON session_assets BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_sessions WHERE session_id = old.session_id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_clips WHERE asset_id = old.asset_id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_event_ai AFTER INSERT ON events BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_events WHERE event_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_event_au AFTER UPDATE ON events BEGIN
    DELETE FROM search_documents WHERE kind = 'event' AND event_id = old.id AND old.id <> new.id;
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_events WHERE event_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_event_ad AFTER DELETE ON events BEGIN
    DELETE FROM search_documents WHERE kind = 'event' AND event_id = old.id;
END;
CREATE TRIGGER search_decision_ai AFTER INSERT ON event_decisions BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_events WHERE event_id = new.event_id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_transcript_ai AFTER INSERT ON transcript_segments BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_transcripts WHERE transcript_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_transcript_au AFTER UPDATE ON transcript_segments BEGIN
    DELETE FROM search_documents
    WHERE kind = 'transcript' AND transcript_id = old.id AND old.id <> new.id;
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_transcripts WHERE transcript_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_transcript_ad AFTER DELETE ON transcript_segments BEGIN
    DELETE FROM search_documents WHERE kind = 'transcript' AND transcript_id = old.id;
END;
CREATE TRIGGER search_project_ai AFTER INSERT ON stories BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_projects WHERE project_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_project_au AFTER UPDATE OF title, session_id, created_at ON stories BEGIN
    INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
        project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
        duration_ms, source_kind, event_type, confidence, review_state)
    SELECT * FROM search_source_projects WHERE project_id = new.id
    ON CONFLICT (doc_key) DO UPDATE SET kind = excluded.kind, session_id = excluded.session_id,
        asset_id = excluded.asset_id, event_id = excluded.event_id,
        transcript_id = excluded.transcript_id, project_id = excluded.project_id,
        title = excluded.title, body = excluded.body,
        start_ms = excluded.start_ms, end_ms = excluded.end_ms,
        source_start_ms = excluded.source_start_ms, source_end_ms = excluded.source_end_ms,
        occurred_at = excluded.occurred_at, duration_ms = excluded.duration_ms,
        source_kind = excluded.source_kind, event_type = excluded.event_type,
        confidence = excluded.confidence, review_state = excluded.review_state,
        index_version = excluded.index_version;
END;
CREATE TRIGGER search_project_ad AFTER DELETE ON stories BEGIN
    DELETE FROM search_documents WHERE kind = 'project' AND project_id = old.id;
END;

-- Initial build from the existing library.
INSERT INTO search_documents (doc_key, kind, session_id, asset_id, event_id, transcript_id,
    project_id, title, body, start_ms, end_ms, source_start_ms, source_end_ms, occurred_at,
    duration_ms, source_kind, event_type, confidence, review_state)
SELECT * FROM search_source_clips
UNION ALL SELECT * FROM search_source_sessions
UNION ALL SELECT * FROM search_source_events
UNION ALL SELECT * FROM search_source_transcripts
UNION ALL SELECT * FROM search_source_projects;
INSERT INTO search_index_state VALUES (
    1, 1, 'current',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
);

-- Collections: the unused 0001 tables are reshaped. A collection is manual (explicit
-- items) or rule-based (a saved search rule evaluated against the index; no items).
-- Items reference exactly one clip, session, event, transcript span or project and
-- disappear with it. Existing rows become manual collections with stable IDs.
CREATE TABLE collections_v2 (
    id          TEXT PRIMARY KEY CHECK (id GLOB 'col_*' AND length(id) = 30),
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(name) BETWEEN 1 AND 80),
    kind        TEXT NOT NULL CHECK (kind IN ('manual', 'rule')),
    rule_json   TEXT CHECK (rule_json IS NULL OR json_valid(rule_json)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK ((kind = 'rule') = (rule_json IS NOT NULL))
);
INSERT INTO collections_v2 (id, name, kind, rule_json, created_at, updated_at)
SELECT 'col_' || printf('%026d', id), substr(name, 1, 80), 'manual', NULL, created_at, created_at
FROM collections;

CREATE TABLE collection_items_v2 (
    id             INTEGER PRIMARY KEY,
    collection_id  TEXT NOT NULL REFERENCES collections_v2 (id) ON DELETE CASCADE,
    asset_id       TEXT REFERENCES media_assets (id) ON DELETE CASCADE,
    session_id     TEXT REFERENCES sessions (id) ON DELETE CASCADE,
    event_id       TEXT REFERENCES events (id) ON DELETE CASCADE,
    transcript_id  INTEGER REFERENCES transcript_segments (id) ON DELETE CASCADE,
    story_id       TEXT REFERENCES stories (id) ON DELETE CASCADE,
    position       INTEGER NOT NULL CHECK (position >= 0),
    added_at       TEXT NOT NULL,
    CHECK ((asset_id IS NOT NULL) + (session_id IS NOT NULL) + (event_id IS NOT NULL)
           + (transcript_id IS NOT NULL) + (story_id IS NOT NULL) = 1),
    UNIQUE (collection_id, position)
);
INSERT INTO collection_items_v2 (id, collection_id, asset_id, session_id, event_id,
    transcript_id, story_id, position, added_at)
SELECT id, 'col_' || printf('%026d', collection_id), NULL, session_id, event_id, NULL, story_id,
       position, added_at
FROM collection_items;

DROP TABLE collection_items;
DROP TABLE collections;
ALTER TABLE collections_v2 RENAME TO collections;
ALTER TABLE collection_items_v2 RENAME TO collection_items;
CREATE UNIQUE INDEX collection_items_asset ON collection_items (collection_id, asset_id)
    WHERE asset_id IS NOT NULL;
CREATE UNIQUE INDEX collection_items_session ON collection_items (collection_id, session_id)
    WHERE session_id IS NOT NULL;
CREATE UNIQUE INDEX collection_items_event ON collection_items (collection_id, event_id)
    WHERE event_id IS NOT NULL;
CREATE UNIQUE INDEX collection_items_transcript ON collection_items (collection_id, transcript_id)
    WHERE transcript_id IS NOT NULL;
CREATE UNIQUE INDEX collection_items_story ON collection_items (collection_id, story_id)
    WHERE story_id IS NOT NULL;
