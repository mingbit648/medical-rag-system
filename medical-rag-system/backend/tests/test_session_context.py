import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.session_context import build_retrieval_query, build_session_summary
from app.repositories.pg_repository import PgRepository


class FakeCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        if not self.responses:
            return None
        return self.responses.pop(0)


class SessionContextTests(unittest.TestCase):
    def test_build_session_summary_keeps_user_facts_only(self):
        summary = build_session_summary(
            [
                {"role": "user", "content": "我是上海员工，公司连续两个月拖欠工资。"},
                {"role": "assistant", "content": "建议先固定考勤、工资条和沟通记录。"},
                {"role": "user", "content": "我还想申请经济补偿。"},
            ],
            max_chars=400,
            max_user_items=4,
            max_assistant_items=2,
            item_chars=80,
        )

        self.assertIn("用户已提供的背景与诉求", summary)
        self.assertIn("拖欠工资", summary)
        self.assertNotIn("固定考勤", summary)

    def test_build_retrieval_query_adds_context_for_short_follow_up(self):
        query = build_retrieval_query(
            "那补偿呢？",
            summary_text="用户在上海，争议点是拖欠工资和违法辞退。",
            recent_messages=[
                {"role": "user", "content": "公司拖欠工资两个月"},
                {"role": "assistant", "content": "建议先固定证据"},
                {"role": "user", "content": "我还被口头辞退了"},
            ],
            short_query_chars=24,
            max_recent_user_messages=2,
            pronoun_pattern=re.compile(r"那|这个|补偿"),
        )

        self.assertIn("会话摘要", query)
        self.assertIn("最近用户问题", query)
        self.assertIn("当前问题", query)
        self.assertIn("口头辞退", query)

    def test_build_retrieval_query_keeps_long_query_clean(self):
        raw_query = "公司违法辞退且未支付工资的情况下，我是否可以同时主张赔偿金和经济补偿？"
        query = build_retrieval_query(
            raw_query,
            summary_text="不会被使用",
            recent_messages=[{"role": "user", "content": "历史问题"}],
            short_query_chars=10,
            max_recent_user_messages=2,
            pronoun_pattern=re.compile(r"那|这个"),
        )
        self.assertEqual(query, raw_query)

    def test_get_active_context_snapshot_returns_none_when_session_has_no_active_summary(self):
        repo = object.__new__(PgRepository)
        cursor = FakeCursor(
            [
                {"active_summary_id": None},
            ]
        )

        snapshot = repo._get_active_context_snapshot(cursor, "s_test")

        self.assertIsNone(snapshot)
        self.assertEqual(len(cursor.executed), 1)


if __name__ == "__main__":
    unittest.main()
