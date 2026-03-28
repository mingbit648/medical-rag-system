import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repositories.pg_repository import PgRepository
from app.services.session_service import SessionService


class RecordingCursor:
    def __init__(self, fetchall_rows=None, fetchone_row=None):
        self.fetchall_rows = fetchall_rows or []
        self.fetchone_row = fetchone_row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.fetchall_rows

    def fetchone(self):
        return self.fetchone_row


class FakeRepo:
    def __init__(self):
        self.sessions = {}
        self.messages = []

    @contextmanager
    def transaction(self):
        yield object()

    def _get_session(self, cur, session_id, user_id=None, for_update=False):
        session = self.sessions.get(session_id)
        if not session:
            return None
        if user_id and session.get("user_id") != user_id:
            return None
        return dict(session)

    def _insert_session(
        self,
        cur,
        *,
        session_id,
        user_id,
        kb_id,
        title,
        created_at,
        updated_at,
        last_active_at,
        message_count,
        status,
        meta_json,
    ):
        self.sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "kb_id": kb_id,
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
            "last_active_at": last_active_at,
            "message_count": message_count,
            "status": status,
            "meta_json": dict(meta_json),
            "preview": meta_json.get("preview", ""),
            "active_summary_id": None,
        }

    def _request_id_exists(self, cur, session_id, request_id):
        return False

    def _find_streaming_message(self, cur, session_id):
        return None

    def _get_next_session_seq(self, cur, session_id):
        return len([item for item in self.messages if item["session_id"] == session_id]) + 1

    def _insert_message(self, cur, **payload):
        self.messages.append(dict(payload))
        return dict(payload)

    def _update_session(
        self,
        cur,
        session_id,
        *,
        title=None,
        status=None,
        updated_at=None,
        last_active_at=None,
        message_count=None,
        active_summary_id=None,
        meta_json=None,
    ):
        session = dict(self.sessions[session_id])
        if title is not None:
            session["title"] = title
        if status is not None:
            session["status"] = status
        if updated_at is not None:
            session["updated_at"] = updated_at
        if last_active_at is not None:
            session["last_active_at"] = last_active_at
        if message_count is not None:
            session["message_count"] = message_count
        if active_summary_id is not None:
            session["active_summary_id"] = active_summary_id
        if meta_json is not None:
            session["meta_json"] = dict(meta_json)
            session["preview"] = meta_json.get("preview", "")
        self.sessions[session_id] = session
        return dict(session)


class TestableSessionService(SessionService):
    def _build_prompt_context(self, cur, session_id):
        return {"summary_text": "", "summary_to_seq": 0, "recent_messages": []}

    def _repair_stale_streams(self, cur, session):
        return None


class SessionServiceTests(unittest.TestCase):
    def test_list_sessions_query_excludes_zero_message_rows(self):
        repo = object.__new__(PgRepository)
        cursor = RecordingCursor(
            [
                {
                    "session_id": "s_keep",
                    "title": "已发送",
                    "status": "active",
                    "created_at": "2026-03-15T00:00:00Z",
                    "updated_at": "2026-03-15T00:00:00Z",
                    "last_active_at": "2026-03-15T00:00:00Z",
                    "message_count": 2,
                    "meta_json": {},
                    "active_summary_id": None,
                }
            ]
        )

        items = repo._list_sessions(cursor, user_id="user_1", kb_id="kb_1", limit=20, status="active")

        self.assertEqual([item["session_id"] for item in items], ["s_keep"])
        self.assertIn("COALESCE(s.message_count, 0) > 0", cursor.executed[0][0])
        self.assertIn("s.kb_id = %s", cursor.executed[0][0])

    def test_mark_empty_sessions_deleted_uses_zero_message_guard(self):
        repo = object.__new__(PgRepository)
        cursor = RecordingCursor()

        repo._mark_empty_sessions_deleted(cursor)

        sql = cursor.executed[0][0]
        self.assertIn("SET status = 'deleted'", sql)
        self.assertIn("COALESCE(s.message_count, 0) = 0", sql)
        self.assertIn("NOT EXISTS", sql)

    def test_get_session_for_update_only_locks_sessions_table(self):
        repo = object.__new__(PgRepository)
        cursor = RecordingCursor(
            fetchone_row={
                "session_id": "s_1",
                "title": "测试会话",
                "status": "active",
                "created_at": "2026-03-15T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
                "last_active_at": "2026-03-15T00:00:00Z",
                "message_count": 1,
                "meta_json": {},
                "active_summary_id": None,
                "kb_name": "我的知识库",
            }
        )

        session = repo._get_session(cursor, "s_1", user_id="user_1", for_update=True)

        self.assertEqual(session["session_id"], "s_1")
        sql = cursor.executed[0][0]
        self.assertIn("LEFT JOIN knowledge_bases kb", sql)
        self.assertIn("FOR UPDATE OF s", sql)
        self.assertNotIn("FOR UPDATE OF kb", sql)

    def test_start_turn_without_session_id_creates_persisted_session(self):
        repo = FakeRepo()
        service = TestableSessionService(repo)

        result = service.start_turn(
            user_id="user_1",
            kb_id="kb_1",
            session_id=None,
            query="公司拖欠工资怎么办？",
            request_id="req_first_turn",
        )

        self.assertTrue(result.session["session_id"].startswith("s_"))
        self.assertEqual(result.session["user_id"], "user_1")
        self.assertEqual(result.session["kb_id"], "kb_1")
        self.assertEqual(result.session["message_count"], 2)
        self.assertEqual(result.user_message["role"], "user")
        self.assertEqual(result.assistant_message["role"], "assistant")
        self.assertEqual(len(repo.messages), 2)
        self.assertEqual(repo.messages[0]["content"], "公司拖欠工资怎么办？")


if __name__ == "__main__":
    unittest.main()
