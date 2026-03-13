import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)


class PgRepository:
    """PostgreSQL 持久层 — 与原 SQLiteRepository 保持相同的方法签名。"""

    def __init__(self, database_url: str, min_conn: int = 1, max_conn: int = 5):
        self._pool = psycopg2.pool.SimpleConnectionPool(
            min_conn, max_conn, dsn=database_url
        )
        logger.info("PostgreSQL connection pool created (%s ~ %s)", min_conn, max_conn)

    # ─── helpers ──────────────────────────────────────────
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
    def _cursor(self, *, dict_cursor: bool = True):
        with self._conn() as conn:
            cur_factory = psycopg2.extras.RealDictCursor if dict_cursor else None
            with conn.cursor(cursor_factory=cur_factory) as cur:
                yield cur

    # ─── documents ────────────────────────────────────────
    def upsert_document(self, payload: Dict[str, Any]) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents(doc_id, title, doc_type, source_url, file_path, created_at, parse_status, meta_json)
                VALUES(%(doc_id)s, %(title)s, %(doc_type)s, %(source_url)s, %(file_name)s, %(created_at)s, %(parse_status)s, %(meta_json)s)
                ON CONFLICT(doc_id) DO UPDATE SET
                    title      = EXCLUDED.title,
                    doc_type   = EXCLUDED.doc_type,
                    source_url = EXCLUDED.source_url,
                    file_path  = EXCLUDED.file_path,
                    parse_status = EXCLUDED.parse_status,
                    meta_json  = EXCLUDED.meta_json
                """,
                {
                    **payload,
                    "meta_json": json.dumps(
                        {"text": payload.get("text", ""), "chunks": payload.get("chunks", 0), "domain": payload.get("domain", "劳动法/通用")},
                        ensure_ascii=False,
                    ),
                },
            )

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
            row = cur.fetchone()
        if not row:
            return None
        return self._doc_row_to_dict(dict(row))

    def list_documents(self) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM documents ORDER BY created_at DESC")
            rows = cur.fetchall()
        return [self._doc_row_to_dict(dict(r)) for r in rows]

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

    @staticmethod
    def _doc_row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        """将 PG 行转为与 SQLite 兼容的 dict 格式。"""
        meta = row.get("meta_json") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        row["text"] = meta.get("text", "")
        row["chunks"] = meta.get("chunks", 0)
        row["file_name"] = row.get("file_path", "")
        return row

    # ─── chunks ───────────────────────────────────────────
    def replace_chunks(self, doc_id: str, chunks: List[Dict[str, Any]]) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
            if chunks:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO chunks(chunk_id, doc_id, chunk_index, chunk_text, start_pos, end_pos, section, article_no, page_start, page_end)
                    VALUES %s
                    """,
                    [
                        (
                            c["chunk_id"], c["doc_id"], c["chunk_index"], c["chunk_text"],
                            c["start_pos"], c["end_pos"],
                            c.get("section"), c.get("article_no"),
                            c.get("page_start"), c.get("page_end"),
                        )
                        for c in chunks
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
                cur.execute(
                    "SELECT * FROM chunks WHERE doc_id = %s ORDER BY chunk_index",
                    (doc_id,),
                )
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
        return [dict(r) for r in rows]

    # ─── citations ────────────────────────────────────────
    def save_citation(self, citation_id: str, chunk_id: str, doc_id: str, payload: Dict[str, Any], created_at: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO citations(citation_id, chunk_id, doc_id, payload_json, created_at)
                VALUES(%s, %s, %s, %s, %s)
                ON CONFLICT(citation_id) DO UPDATE SET
                    chunk_id     = EXCLUDED.chunk_id,
                    doc_id       = EXCLUDED.doc_id,
                    payload_json = EXCLUDED.payload_json
                """,
                (citation_id, chunk_id, doc_id, json.dumps(payload, ensure_ascii=False), created_at),
            )

    def get_citation(self, citation_id: str) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM citations WHERE citation_id = %s", (citation_id,))
            row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        pj = data.get("payload_json")
        if isinstance(pj, str):
            data["payload"] = json.loads(pj)
        elif isinstance(pj, dict):
            data["payload"] = pj
        else:
            data["payload"] = {}
        return data

    # ─── messages ─────────────────────────────────────────
    def append_message(self, msg_id: str, session_id: str, role: str, content: str, created_at: str) -> None:
        with self._cursor() as cur:
            # 确保 session 存在
            cur.execute(
                """
                INSERT INTO sessions(session_id, created_at, last_active_at)
                VALUES(%s, %s, %s)
                ON CONFLICT(session_id) DO UPDATE SET last_active_at = EXCLUDED.last_active_at
                """,
                (session_id, created_at, created_at),
            )
            cur.execute(
                """
                INSERT INTO messages(msg_id, session_id, role, content, created_at)
                VALUES(%s, %s, %s, %s, %s)
                """,
                (msg_id, session_id, role, content, created_at),
            )

    def list_messages(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT msg_id, session_id, role, content, created_at
                FROM messages
                WHERE session_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ─── runs ─────────────────────────────────────────────
    def save_run(self, run_id: str, mode: str, config: Dict[str, Any], metrics: Dict[str, Any], created_at: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs(run_id, mode, config_json, metrics_json, created_at)
                VALUES(%s, %s, %s, %s, %s)
                ON CONFLICT(run_id) DO UPDATE SET
                    mode         = EXCLUDED.mode,
                    config_json  = EXCLUDED.config_json,
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
        cj = data.get("config_json")
        mj = data.get("metrics_json")
        data["config"] = json.loads(cj) if isinstance(cj, str) else (cj or {})
        data["metrics"] = json.loads(mj) if isinstance(mj, str) else (mj or {})
        return data

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            cj = item.get("config_json")
            mj = item.get("metrics_json")
            item["config"] = json.loads(cj) if isinstance(cj, str) else (cj or {})
            item["metrics"] = json.loads(mj) if isinstance(mj, str) else (mj or {})
            result.append(item)
        return result
