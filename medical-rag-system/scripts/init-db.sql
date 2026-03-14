CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    title        TEXT,
    doc_type     TEXT NOT NULL DEFAULT 'pdf',
    source_url   TEXT,
    file_path    TEXT,
    content_text TEXT,
    published_at TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    parse_status TEXT NOT NULL DEFAULT 'imported',
    meta_json    JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    chunk_text   TEXT NOT NULL,
    section      TEXT,
    article_no   TEXT,
    page_start   INTEGER,
    page_end     INTEGER,
    start_pos    INTEGER,
    end_pos      INTEGER,
    norm_hash    TEXT,
    locator_json JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS indices_state (
    doc_id       TEXT PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
    bm25_ready   BOOLEAN NOT NULL DEFAULT FALSE,
    faiss_ready  BOOLEAN NOT NULL DEFAULT FALSE,
    bm25_version TEXT,
    embed_model  TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    title             TEXT NOT NULL DEFAULT '新对话',
    status            TEXT NOT NULL DEFAULT 'active',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    message_count     INTEGER NOT NULL DEFAULT 0,
    active_summary_id TEXT,
    meta_json         JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id        TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    session_seq   INTEGER NOT NULL,
    role          TEXT NOT NULL,
    message_type  TEXT NOT NULL DEFAULT 'message',
    status        TEXT NOT NULL DEFAULT 'completed',
    request_id    TEXT,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at  TIMESTAMPTZ,
    meta_json     JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS session_context_snapshots (
    snapshot_id   TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    from_seq      INTEGER NOT NULL,
    to_seq        INTEGER NOT NULL,
    summary_text  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    meta_json     JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    mode         TEXT NOT NULL,
    config_json  JSONB DEFAULT '{}'::jsonb,
    metrics_json JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS citations (
    citation_id  TEXT PRIMARY KEY,
    chunk_id     TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    message_id   TEXT REFERENCES messages(msg_id) ON DELETE CASCADE,
    payload_json JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS uidx_messages_session_seq ON messages(session_id, session_seq);
CREATE INDEX IF NOT EXISTS idx_messages_session_status ON messages(session_id, status);
CREATE INDEX IF NOT EXISTS idx_messages_session_request_id ON messages(session_id, request_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status_updated_at ON sessions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_session_to_seq ON session_context_snapshots(session_id, to_seq DESC);
CREATE INDEX IF NOT EXISTS idx_citations_chunk_id ON citations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_citations_doc_id ON citations(doc_id);
CREATE INDEX IF NOT EXISTS idx_citations_message_id ON citations(message_id);
