CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    display_name   TEXT,
    role           TEXT NOT NULL DEFAULT 'user',
    status         TEXT NOT NULL DEFAULT 'active',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    kb_id          TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT,
    status         TEXT NOT NULL DEFAULT 'active',
    created_by     TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    owner_user_id  TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    visibility     TEXT NOT NULL DEFAULT 'system',
    is_default     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    kb_id        TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE RESTRICT,
    title        TEXT,
    doc_type     TEXT NOT NULL DEFAULT 'pdf',
    source_url   TEXT,
    file_path    TEXT,
    content_text TEXT,
    published_at TEXT,
    uploaded_by  TEXT REFERENCES users(user_id) ON DELETE SET NULL,
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
    user_id           TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kb_id             TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE RESTRICT,
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
    kb_id        TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE RESTRICT,
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

CREATE TABLE IF NOT EXISTS auth_sessions (
    auth_session_id     TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_token_hash  TEXT NOT NULL UNIQUE,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS index_jobs (
    job_id         TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    kb_id          TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE RESTRICT,
    requested_by   TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    status         TEXT NOT NULL DEFAULT 'queued',
    attempts       INTEGER NOT NULL DEFAULT 0,
    max_attempts   INTEGER NOT NULL DEFAULT 3,
    payload_json   JSONB DEFAULT '{}'::jsonb,
    error_message  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_documents_kb_id ON documents(kb_id);
CREATE INDEX IF NOT EXISTS idx_documents_uploaded_by ON documents(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_visibility_owner ON knowledge_bases(visibility, owner_user_id);
CREATE INDEX IF NOT EXISTS idx_index_jobs_status_created_at ON index_jobs(status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_index_jobs_doc_id ON index_jobs(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS uidx_messages_session_seq ON messages(session_id, session_seq);
CREATE INDEX IF NOT EXISTS idx_messages_session_status ON messages(session_id, status);
CREATE INDEX IF NOT EXISTS idx_messages_session_request_id ON messages(session_id, request_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_updated_at ON sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_kb_id ON sessions(kb_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status_updated_at ON sessions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_session_to_seq ON session_context_snapshots(session_id, to_seq DESC);
CREATE INDEX IF NOT EXISTS idx_citations_chunk_id ON citations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_citations_doc_id ON citations(doc_id);
CREATE INDEX IF NOT EXISTS idx_citations_message_id ON citations(message_id);
CREATE INDEX IF NOT EXISTS idx_runs_kb_id ON runs(kb_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS uidx_knowledge_bases_private_owner_name
    ON knowledge_bases(owner_user_id, name)
    WHERE visibility = 'private';
CREATE UNIQUE INDEX IF NOT EXISTS uidx_knowledge_bases_system_name
    ON knowledge_bases(name)
    WHERE visibility = 'system';
CREATE UNIQUE INDEX IF NOT EXISTS uidx_knowledge_bases_default_private_owner
    ON knowledge_bases(owner_user_id)
    WHERE visibility = 'private' AND is_default;
CREATE UNIQUE INDEX IF NOT EXISTS uidx_index_jobs_doc_active
    ON index_jobs(doc_id)
    WHERE status IN ('queued', 'running');
