-- ============================================================
-- 法律辅助咨询 RAG 系统 - 数据库初始化脚本
-- 按技术方案 6.x 节创建完整表结构
-- ============================================================

-- 6.1 文档表
CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    title        TEXT,
    doc_type     TEXT NOT NULL DEFAULT 'pdf',       -- pdf / html / txt
    source_url   TEXT,
    file_path    TEXT,
    published_at TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    parse_status TEXT NOT NULL DEFAULT 'imported',   -- imported / parsed / indexed / error
    meta_json    JSONB DEFAULT '{}'::jsonb
);

-- 6.2 分块表
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    chunk_text   TEXT NOT NULL,
    section      TEXT,
    article_no   TEXT,
    page_start   INTEGER,
    page_end     INTEGER,
    start_pos    INTEGER,        -- 原文字符偏移起点
    end_pos      INTEGER,        -- 原文字符偏移终点
    norm_hash    TEXT,           -- 规范化后 hash（辅助匹配）
    locator_json JSONB DEFAULT '{}'::jsonb
);

-- 6.3 索引状态表
CREATE TABLE IF NOT EXISTS indices_state (
    doc_id       TEXT PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
    bm25_ready   BOOLEAN NOT NULL DEFAULT FALSE,
    faiss_ready  BOOLEAN NOT NULL DEFAULT FALSE,
    bm25_version TEXT,
    embed_model  TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6.4 会话表
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6.4 消息表
CREATE TABLE IF NOT EXISTS messages (
    msg_id       TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role         TEXT NOT NULL,         -- user / assistant / system
    content      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6.5 实验运行表
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    mode         TEXT NOT NULL,         -- baseline_vector / hybrid_rerank
    config_json  JSONB DEFAULT '{}'::jsonb,
    metrics_json JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 引用记录表（支持引用溯源与高亮查看）
CREATE TABLE IF NOT EXISTS citations (
    citation_id  TEXT PRIMARY KEY,
    chunk_id     TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    payload_json JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============ 索引 ============
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id      ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_citations_chunk_id  ON citations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_citations_doc_id    ON citations(doc_id);

-- ============ 更新时间戳触发器 ============
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_indices_state_updated_at
    BEFORE UPDATE ON indices_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE FUNCTION update_last_active_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_active_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_sessions_last_active
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_last_active_at_column();
