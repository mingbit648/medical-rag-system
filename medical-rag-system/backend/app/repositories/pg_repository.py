import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)


DEFAULT_SESSION_TITLE = "新对话"


class PgRepository:
    def __init__(self, database_url: str, min_conn: int = 1, max_conn: int = 5):
        self._pool = psycopg2.pool.SimpleConnectionPool(min_conn, max_conn, dsn=database_url)
        self._ensure_schema_extensions()
        logger.info("PostgreSQL connection pool created (%s ~ %s)", min_conn, max_conn)

    def _ensure_schema_extensions(self) -> None:
        with self._cursor(dict_cursor=False) as cur:
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_path TEXT")
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_text TEXT")
            cur.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS locator_json JSONB DEFAULT '{}'::jsonb")

            cur.execute(f"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '{DEFAULT_SESSION_TITLE}'")
            cur.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
            cur.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
            cur.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS message_count INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS active_summary_id TEXT")
            cur.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS meta_json JSONB DEFAULT '{}'::jsonb")

            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS session_seq INTEGER")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_type TEXT NOT NULL DEFAULT 'message'")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed'")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS request_id TEXT")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS meta_json JSONB DEFAULT '{}'::jsonb")

            cur.execute("ALTER TABLE citations ADD COLUMN IF NOT EXISTS message_id TEXT")
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'citations_message_id_fkey'
                    ) THEN
                        ALTER TABLE citations
                        ADD CONSTRAINT citations_message_id_fkey
                        FOREIGN KEY (message_id) REFERENCES messages(msg_id) ON DELETE CASCADE;
                    END IF;
                END $$;
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_context_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    from_seq INTEGER NOT NULL,
                    to_seq INTEGER NOT NULL,
                    summary_text TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    meta_json JSONB DEFAULT '{}'::jsonb
                )
                """
            )

            cur.execute(
                """
                UPDATE documents
                SET
                    content_text = COALESCE(content_text, meta_json->>'text'),
                    meta_json = CASE
                        WHEN meta_json IS NULL THEN '{}'::jsonb
                        WHEN meta_json ? 'text' THEN meta_json - 'text'
                        ELSE meta_json
                    END
                WHERE content_text IS NULL
                   OR (meta_json IS NOT NULL AND meta_json ? 'text')
                """
            )

            cur.execute(
                """
                UPDATE sessions
                SET
                    title = COALESCE(NULLIF(title, ''), %s),
                    status = COALESCE(NULLIF(status, ''), 'active'),
                    updated_at = COALESCE(updated_at, last_active_at, created_at),
                    meta_json = COALESCE(meta_json, '{}'::jsonb)
                """,
                (DEFAULT_SESSION_TITLE,),
            )
            cur.execute(
                """
                UPDATE sessions s
                SET message_count = COALESCE(m.msg_count, 0)
                FROM (
                    SELECT session_id, COUNT(*) AS msg_count
                    FROM messages
                    GROUP BY session_id
                ) m
                WHERE s.session_id = m.session_id
                  AND s.message_count <> COALESCE(m.msg_count, 0)
                """
            )
            cur.execute("UPDATE sessions SET message_count = 0 WHERE message_count IS NULL")

            cur.execute(
                """
                UPDATE messages
                SET
                    message_type = CASE
                        WHEN role = 'user' THEN 'question'
                        WHEN role = 'assistant' THEN 'answer'
                        ELSE 'message'
                    END,
                    status = COALESCE(NULLIF(status, ''), 'completed'),
                    updated_at = COALESCE(updated_at, created_at),
                    completed_at = CASE
                        WHEN completed_at IS NOT NULL THEN completed_at
                        WHEN COALESCE(NULLIF(status, ''), 'completed') IN ('completed', 'error') THEN created_at
                        ELSE NULL
                    END,
                    meta_json = COALESCE(meta_json, '{}'::jsonb)
                """
            )
            cur.execute(
                """
                UPDATE messages
                SET session_seq = NULL
                WHERE session_seq IS NOT NULL
                """
            )
            cur.execute(
                """
                WITH seq_source AS (
                    SELECT
                        msg_id,
                        ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at ASC, msg_id ASC) AS seq_no
                    FROM messages
                )
                UPDATE messages m
                SET session_seq = seq_source.seq_no
                FROM seq_source
                WHERE m.msg_id = seq_source.msg_id
                """
            )

            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_seq ON messages(session_id, session_seq)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_status ON messages(session_id, status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_request_id ON messages(session_id, request_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status_updated_at ON sessions(status, updated_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_session_snapshots_session_to_seq ON session_context_snapshots(session_id, to_seq DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_citations_chunk_id ON citations(chunk_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_citations_doc_id ON citations(doc_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_citations_message_id ON citations(message_id)")
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes WHERE indexname = 'uidx_messages_session_seq'
                    ) THEN
                        CREATE UNIQUE INDEX uidx_messages_session_seq ON messages(session_id, session_seq);
                    END IF;
                END $$;
                """
            )

    @contextmanager
    def _conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    @contextmanager
    def transaction(self, *, dict_cursor: bool = True):
        with self._conn() as conn:
            cur_factory = psycopg2.extras.RealDictCursor if dict_cursor else None
            with conn.cursor(cursor_factory=cur_factory) as cur:
                yield cur

    @contextmanager
    def _cursor(self, *, dict_cursor: bool = True):
        with self.transaction(dict_cursor=dict_cursor) as cur:
            yield cur

    @staticmethod
    def _load_json(value: Any, default: Any):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default
        return value if value is not None else default

    @staticmethod
    def _doc_row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        meta = row.get("meta_json") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        row["meta_json"] = meta
        row["text"] = row.get("content_text") or meta.get("text", "")
        row["chunks"] = meta.get("chunks", 0)
        row["file_name"] = meta.get("original_file_name") or row.get("file_path", "")
        row["original_file_name"] = meta.get("original_file_name")
        row["mime_type"] = meta.get("mime_type")
        row["has_original_file"] = bool(meta.get("has_original_file"))
        row["viewer_mode"] = meta.get("viewer_mode")
        row["source_version"] = meta.get("source_version")
        row["page_spans"] = meta.get("page_spans") or []
        row["paragraph_spans"] = meta.get("paragraph_spans") or []
        return row

    @classmethod
    def _session_row_to_dict(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        meta = cls._load_json(row.get("meta_json"), {})
        row["meta_json"] = meta
        row["title"] = (row.get("title") or "").strip() or DEFAULT_SESSION_TITLE
        row["preview"] = meta.get("preview", "")
        row["last_message_role"] = meta.get("last_message_role")
        row["last_user_query"] = meta.get("last_user_query")
        return row

    @classmethod
    def _message_row_to_dict(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        row["meta_json"] = cls._load_json(row.get("meta_json"), {})
        row["message_id"] = row.get("msg_id")
        row.setdefault("citations", [])
        return row

    @classmethod
    def _snapshot_row_to_dict(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        row["meta_json"] = cls._load_json(row.get("meta_json"), {})
        return row

    @classmethod
    def _citation_row_to_dict(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        row["payload"] = cls._load_json(row.get("payload_json"), {})
        return row

    def upsert_document(self, payload: Dict[str, Any]) -> None:
        meta = payload.get("meta") or {
            "chunks": payload.get("chunks", 0),
            "domain": payload.get("domain", "劳动法/通用"),
        }
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents(
                    doc_id, title, doc_type, source_url, file_path, content_text, created_at, parse_status, meta_json
                )
                VALUES(
                    %(doc_id)s, %(title)s, %(doc_type)s, %(source_url)s, %(file_path)s,
                    %(content_text)s, %(created_at)s, %(parse_status)s, %(meta_json)s
                )
                ON CONFLICT(doc_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    doc_type = EXCLUDED.doc_type,
                    source_url = EXCLUDED.source_url,
                    file_path = EXCLUDED.file_path,
                    content_text = EXCLUDED.content_text,
                    parse_status = EXCLUDED.parse_status,
                    meta_json = EXCLUDED.meta_json
                """,
                {
                    **payload,
                    "file_path": payload.get("file_path") or payload.get("file_name"),
                    "content_text": payload.get("content_text") or payload.get("text", ""),
                    "meta_json": json.dumps(meta, ensure_ascii=False),
                },
            )

    @staticmethod
    def _document_select_columns(include_text: bool) -> str:
        base_columns = [
            "doc_id",
            "title",
            "doc_type",
            "source_url",
            "file_path",
            "published_at",
            "created_at",
            "parse_status",
            "meta_json",
        ]
        if include_text:
            base_columns.append("content_text")
        return ", ".join(base_columns)

    def get_document(self, doc_id: str, *, include_text: bool = True) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {self._document_select_columns(include_text)} FROM documents WHERE doc_id = %s",
                (doc_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return self._doc_row_to_dict(dict(row))

    def list_documents(self, *, include_text: bool = True) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {self._document_select_columns(include_text)} FROM documents ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
        return [self._doc_row_to_dict(dict(row)) for row in rows]

    def delete_document(self, doc_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM citations WHERE doc_id = %s", (doc_id,))
            cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
            cur.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))
            return cur.rowcount > 0

    def update_document_index_status(self, doc_id: str, parse_status: str, chunks: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET parse_status = %s,
                    meta_json = jsonb_set(COALESCE(meta_json, '{}'::jsonb), '{chunks}', %s::jsonb)
                WHERE doc_id = %s
                """,
                (parse_status, json.dumps(chunks), doc_id),
            )

    def replace_chunks(self, doc_id: str, chunks: List[Dict[str, Any]]) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
            if not chunks:
                return
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO chunks(
                    chunk_id, doc_id, chunk_index, chunk_text, start_pos, end_pos,
                    section, article_no, page_start, page_end, locator_json
                )
                VALUES %s
                """,
                [
                    (
                        chunk["chunk_id"],
                        chunk["doc_id"],
                        chunk["chunk_index"],
                        chunk["chunk_text"],
                        chunk["start_pos"],
                        chunk["end_pos"],
                        chunk.get("section"),
                        chunk.get("article_no"),
                        chunk.get("page_start"),
                        chunk.get("page_end"),
                        json.dumps(chunk.get("locator_json") or {}, ensure_ascii=False),
                    )
                    for chunk in chunks
                ],
            )

    def list_chunks(self, doc_id: Optional[str] = None, indexed_only: bool = False) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            if doc_id and indexed_only:
                cur.execute(
                    """
                    SELECT c.* FROM chunks c
                    JOIN documents d ON c.doc_id = d.doc_id
                    WHERE c.doc_id = %s AND d.parse_status = 'indexed'
                    ORDER BY c.doc_id, c.chunk_index
                    """,
                    (doc_id,),
                )
            elif doc_id:
                cur.execute("SELECT * FROM chunks WHERE doc_id = %s ORDER BY chunk_index", (doc_id,))
            elif indexed_only:
                cur.execute(
                    """
                    SELECT c.* FROM chunks c
                    JOIN documents d ON c.doc_id = d.doc_id
                    WHERE d.parse_status = 'indexed'
                    ORDER BY c.doc_id, c.chunk_index
                    """
                )
            else:
                cur.execute("SELECT * FROM chunks ORDER BY doc_id, chunk_index")
            rows = cur.fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["locator_json"] = self._load_json(item.get("locator_json"), {})
            results.append(item)
        return results

    def save_citation(
        self,
        citation_id: str,
        chunk_id: str,
        doc_id: str,
        payload: Dict[str, Any],
        created_at: str,
        message_id: Optional[str] = None,
    ) -> None:
        with self.transaction() as cur:
            self._save_citation(
                cur,
                citation_id=citation_id,
                chunk_id=chunk_id,
                doc_id=doc_id,
                payload=payload,
                created_at=created_at,
                message_id=message_id,
            )

    def _save_citation(
        self,
        cur,
        *,
        citation_id: str,
        chunk_id: str,
        doc_id: str,
        payload: Dict[str, Any],
        created_at: str,
        message_id: Optional[str],
    ) -> None:
        cur.execute(
            """
            INSERT INTO citations(citation_id, chunk_id, doc_id, message_id, payload_json, created_at)
            VALUES(%s, %s, %s, %s, %s, %s)
            ON CONFLICT(citation_id) DO UPDATE SET
                chunk_id = EXCLUDED.chunk_id,
                doc_id = EXCLUDED.doc_id,
                message_id = EXCLUDED.message_id,
                payload_json = EXCLUDED.payload_json
            """,
            (citation_id, chunk_id, doc_id, message_id, json.dumps(payload, ensure_ascii=False), created_at),
        )

    def get_citation(self, citation_id: str) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM citations WHERE citation_id = %s", (citation_id,))
            row = cur.fetchone()
        if not row:
            return None
        return self._citation_row_to_dict(dict(row))

    def create_session(
        self,
        *,
        session_id: str,
        title: str,
        created_at: str,
        updated_at: str,
        last_active_at: str,
        message_count: int,
        status: str,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self.transaction() as cur:
            return self._insert_session(
                cur,
                session_id=session_id,
                title=title,
                created_at=created_at,
                updated_at=updated_at,
                last_active_at=last_active_at,
                message_count=message_count,
                status=status,
                meta_json=meta_json,
            )

    def _insert_session(
        self,
        cur,
        *,
        session_id: str,
        title: str,
        created_at: str,
        updated_at: str,
        last_active_at: str,
        message_count: int,
        status: str,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cur.execute(
            """
            INSERT INTO sessions(
                session_id, title, status, created_at, updated_at, last_active_at, message_count, meta_json
            )
            VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(session_id) DO UPDATE SET
                title = EXCLUDED.title,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at,
                last_active_at = EXCLUDED.last_active_at,
                message_count = EXCLUDED.message_count,
                meta_json = EXCLUDED.meta_json
            RETURNING *
            """,
            (
                session_id,
                title or DEFAULT_SESSION_TITLE,
                status,
                created_at,
                updated_at,
                last_active_at,
                message_count,
                json.dumps(meta_json or {}, ensure_ascii=False),
            ),
        )
        row = cur.fetchone()
        return self._session_row_to_dict(dict(row))

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.transaction() as cur:
            return self._get_session(cur, session_id)

    def _get_session(self, cur, session_id: str, for_update: bool = False) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM sessions WHERE session_id = %s"
        if for_update:
            sql += " FOR UPDATE"
        cur.execute(sql, (session_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._session_row_to_dict(dict(row))

    def list_sessions(self, limit: int = 20, status: Optional[str] = "active") -> List[Dict[str, Any]]:
        with self.transaction() as cur:
            return self._list_sessions(cur, limit=limit, status=status)

    def _list_sessions(self, cur, *, limit: int, status: Optional[str] = "active") -> List[Dict[str, Any]]:
        cur.execute(
            """
            SELECT *
            FROM sessions
            WHERE (%s IS NULL OR status = %s)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT %s
            """,
            (status, status, limit),
        )
        rows = cur.fetchall()
        return [self._session_row_to_dict(dict(row)) for row in rows]

    def update_session(
        self,
        *,
        session_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        updated_at: Optional[str] = None,
        last_active_at: Optional[str] = None,
        message_count: Optional[int] = None,
        active_summary_id: Optional[str] = None,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        with self.transaction() as cur:
            return self._update_session(
                cur,
                session_id,
                title=title,
                status=status,
                updated_at=updated_at,
                last_active_at=last_active_at,
                message_count=message_count,
                active_summary_id=active_summary_id,
                meta_json=meta_json,
            )

    def _update_session(
        self,
        cur,
        session_id: str,
        *,
        title: Optional[str] = None,
        status: Optional[str] = None,
        updated_at: Optional[str] = None,
        last_active_at: Optional[str] = None,
        message_count: Optional[int] = None,
        active_summary_id: Optional[str] = None,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        fields: List[str] = []
        params: List[Any] = []

        if title is not None:
            fields.append("title = %s")
            params.append(title or DEFAULT_SESSION_TITLE)
        if status is not None:
            fields.append("status = %s")
            params.append(status)
        if updated_at is not None:
            fields.append("updated_at = %s")
            params.append(updated_at)
        if last_active_at is not None:
            fields.append("last_active_at = %s")
            params.append(last_active_at)
        if message_count is not None:
            fields.append("message_count = %s")
            params.append(message_count)
        if active_summary_id is not None:
            fields.append("active_summary_id = %s")
            params.append(active_summary_id)
        if meta_json is not None:
            fields.append("meta_json = %s")
            params.append(json.dumps(meta_json, ensure_ascii=False))

        if not fields:
            return self._get_session(cur, session_id)

        params.append(session_id)
        cur.execute(
            f"""
            UPDATE sessions
            SET {", ".join(fields)}
            WHERE session_id = %s
            RETURNING *
            """,
            params,
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._session_row_to_dict(dict(row))

    def _get_next_session_seq(self, cur, session_id: str) -> int:
        cur.execute("SELECT COALESCE(MAX(session_seq), 0) AS max_seq FROM messages WHERE session_id = %s", (session_id,))
        row = cur.fetchone() or {}
        return int((row.get("max_seq") or 0) + 1)

    def _request_id_exists(self, cur, session_id: str, request_id: str) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM messages
            WHERE session_id = %s AND request_id = %s
            LIMIT 1
            """,
            (session_id, request_id),
        )
        return cur.fetchone() is not None

    def _insert_message(
        self,
        cur,
        *,
        msg_id: str,
        session_id: str,
        session_seq: int,
        role: str,
        content: str,
        created_at: str,
        updated_at: str,
        completed_at: Optional[str],
        status: str,
        request_id: Optional[str],
        message_type: str,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cur.execute(
            """
            INSERT INTO messages(
                msg_id, session_id, session_seq, role, content, created_at, updated_at,
                completed_at, status, request_id, message_type, meta_json
            )
            VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                msg_id,
                session_id,
                session_seq,
                role,
                content,
                created_at,
                updated_at,
                completed_at,
                status,
                request_id,
                message_type,
                json.dumps(meta_json or {}, ensure_ascii=False),
            ),
        )
        row = cur.fetchone()
        return self._message_row_to_dict(dict(row))

    def _get_message(self, cur, msg_id: str, for_update: bool = False) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM messages WHERE msg_id = %s"
        if for_update:
            sql += " FOR UPDATE"
        cur.execute(sql, (msg_id,))
        row = cur.fetchone()
        if not row:
            return None
        message = self._message_row_to_dict(dict(row))
        message["citations"] = self._list_citations_for_messages(cur, [msg_id]).get(msg_id, [])
        return message

    def _update_message(
        self,
        cur,
        msg_id: str,
        *,
        content: Optional[str] = None,
        status: Optional[str] = None,
        updated_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        fields: List[str] = []
        params: List[Any] = []

        if content is not None:
            fields.append("content = %s")
            params.append(content)
        if status is not None:
            fields.append("status = %s")
            params.append(status)
        if updated_at is not None:
            fields.append("updated_at = %s")
            params.append(updated_at)
        if completed_at is not None or status == "streaming":
            fields.append("completed_at = %s")
            params.append(completed_at)
        if meta_json is not None:
            fields.append("meta_json = %s")
            params.append(json.dumps(meta_json, ensure_ascii=False))

        if not fields:
            return self._get_message(cur, msg_id)

        params.append(msg_id)
        cur.execute(
            f"""
            UPDATE messages
            SET {", ".join(fields)}
            WHERE msg_id = %s
            RETURNING *
            """,
            params,
        )
        row = cur.fetchone()
        if not row:
            return None
        message = self._message_row_to_dict(dict(row))
        message["citations"] = self._list_citations_for_messages(cur, [msg_id]).get(msg_id, [])
        return message

    def list_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_seq: Optional[int] = None,
        after_seq: Optional[int] = None,
        statuses: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        with self.transaction() as cur:
            return self._list_messages(
                cur,
                session_id=session_id,
                limit=limit,
                before_seq=before_seq,
                after_seq=after_seq,
                statuses=list(statuses) if statuses else None,
                include_citations=True,
            )

    def _list_messages(
        self,
        cur,
        *,
        session_id: str,
        limit: int,
        before_seq: Optional[int] = None,
        after_seq: Optional[int] = None,
        statuses: Optional[Sequence[str]] = None,
        include_citations: bool = True,
    ) -> List[Dict[str, Any]]:
        where_clauses = ["session_id = %s"]
        params: List[Any] = [session_id]

        if before_seq is not None:
            where_clauses.append("session_seq < %s")
            params.append(before_seq)
        if after_seq is not None:
            where_clauses.append("session_seq > %s")
            params.append(after_seq)
        if statuses:
            where_clauses.append("status = ANY(%s)")
            params.append(list(statuses))

        params.append(limit)
        cur.execute(
            f"""
            SELECT *
            FROM (
                SELECT *
                FROM messages
                WHERE {' AND '.join(where_clauses)}
                ORDER BY session_seq DESC
                LIMIT %s
            ) recent
            ORDER BY session_seq ASC
            """,
            params,
        )
        rows = [self._message_row_to_dict(dict(row)) for row in cur.fetchall()]
        if not include_citations or not rows:
            return rows

        citations_by_message = self._list_citations_for_messages(cur, [row["msg_id"] for row in rows])
        for row in rows:
            row["citations"] = citations_by_message.get(row["msg_id"], [])
        return rows

    def _list_citations_for_messages(self, cur, message_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        if not message_ids:
            return {}
        cur.execute(
            """
            SELECT *
            FROM citations
            WHERE message_id = ANY(%s)
            ORDER BY created_at ASC
            """,
            (message_ids,),
        )
        result: Dict[str, List[Dict[str, Any]]] = {}
        for row in cur.fetchall():
            item = self._citation_row_to_dict(dict(row))
            message_id = item.get("message_id")
            payload = item.get("payload") or {}
            if not message_id:
                continue
            result.setdefault(message_id, []).append(payload)
        return result

    def _find_streaming_message(self, cur, session_id: str) -> Optional[Dict[str, Any]]:
        cur.execute(
            """
            SELECT *
            FROM messages
            WHERE session_id = %s AND status = 'streaming'
            ORDER BY session_seq DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._message_row_to_dict(dict(row))

    def _delete_citations_for_message(self, cur, message_id: str) -> None:
        cur.execute("DELETE FROM citations WHERE message_id = %s", (message_id,))

    def _insert_context_snapshot(
        self,
        cur,
        *,
        snapshot_id: str,
        session_id: str,
        from_seq: int,
        to_seq: int,
        summary_text: str,
        created_at: str,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cur.execute(
            """
            INSERT INTO session_context_snapshots(
                snapshot_id, session_id, from_seq, to_seq, summary_text, created_at, updated_at, meta_json
            )
            VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                snapshot_id,
                session_id,
                from_seq,
                to_seq,
                summary_text,
                created_at,
                created_at,
                json.dumps(meta_json or {}, ensure_ascii=False),
            ),
        )
        row = cur.fetchone()
        return self._snapshot_row_to_dict(dict(row))

    def _get_active_context_snapshot(self, cur, session_id: str) -> Optional[Dict[str, Any]]:
        cur.execute(
            """
            SELECT active_summary_id
            FROM sessions
            WHERE session_id = %s
            """,
            (session_id,),
        )
        session_row = cur.fetchone()
        if not session_row:
            return None

        active_summary_id = session_row.get("active_summary_id")
        if not active_summary_id:
            return None

        cur.execute(
            """
            SELECT *
            FROM session_context_snapshots
            WHERE snapshot_id = %s
              AND session_id = %s
            """,
            (active_summary_id, session_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._snapshot_row_to_dict(dict(row))

    def _set_active_context_snapshot(self, cur, session_id: str, snapshot_id: str) -> Optional[Dict[str, Any]]:
        return self._update_session(cur, session_id, active_summary_id=snapshot_id)

    def _clear_active_context_snapshot(self, cur, session_id: str) -> Optional[Dict[str, Any]]:
        cur.execute(
            """
            UPDATE sessions
            SET active_summary_id = NULL
            WHERE session_id = %s
            RETURNING *
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._session_row_to_dict(dict(row))

    def append_message(self, msg_id: str, session_id: str, role: str, content: str, created_at: str) -> None:
        with self.transaction() as cur:
            session = self._get_session(cur, session_id, for_update=True)
            if session is None:
                session = self._insert_session(
                    cur,
                    session_id=session_id,
                    title=DEFAULT_SESSION_TITLE,
                    created_at=created_at,
                    updated_at=created_at,
                    last_active_at=created_at,
                    message_count=0,
                    status="active",
                    meta_json={},
                )
            next_seq = self._get_next_session_seq(cur, session_id)
            self._insert_message(
                cur,
                msg_id=msg_id,
                session_id=session_id,
                session_seq=next_seq,
                role=role,
                content=content,
                created_at=created_at,
                updated_at=created_at,
                completed_at=created_at,
                status="completed",
                request_id=None,
                message_type="question" if role == "user" else "answer" if role == "assistant" else "message",
                meta_json={},
            )
            self._update_session(
                cur,
                session_id,
                updated_at=created_at,
                last_active_at=created_at,
                message_count=(session.get("message_count") or 0) + 1,
                meta_json=session.get("meta_json") or {},
            )

    def save_run(self, run_id: str, mode: str, config: Dict[str, Any], metrics: Dict[str, Any], created_at: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs(run_id, mode, config_json, metrics_json, created_at)
                VALUES(%s, %s, %s, %s, %s)
                ON CONFLICT(run_id) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    config_json = EXCLUDED.config_json,
                    metrics_json = EXCLUDED.metrics_json
                """,
                (run_id, mode, json.dumps(config, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False), created_at),
            )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["config"] = self._load_json(data.get("config_json"), {})
        data["metrics"] = self._load_json(data.get("metrics_json"), {})
        return data

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["config"] = self._load_json(item.get("config_json"), {})
            item["metrics"] = self._load_json(item.get("metrics_json"), {})
            result.append(item)
        return result
