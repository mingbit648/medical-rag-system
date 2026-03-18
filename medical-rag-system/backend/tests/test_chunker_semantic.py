import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.chunker import CHUNK_STRATEGY_VERSION, chunk_text


class SemanticChunkerTests(unittest.TestCase):
    def test_law_chunking_uses_article_units_and_stable_ids(self):
        text = "\n".join(
            [
                "中华人民共和国劳动法",
                "第一章 总则",
                "第一条 为了保护劳动者的合法权益，调整劳动关系，建立和维护适应社会主义市场经济的劳动制度，制定本法。",
                "第二条 在中华人民共和国境内的企业、个体经济组织和与之形成劳动关系的劳动者，适用本法。",
            ]
        )
        meta = {"source_fingerprint": "fingerprint_001", "title": "中华人民共和国劳动法"}

        first = chunk_text(text, 120, 20, "doc_random_a", doc_type="docx", document_meta=meta)
        second = chunk_text(text, 120, 20, "doc_random_b", doc_type="docx", document_meta=meta)

        self.assertEqual([item["chunk_id"] for item in first], [item["chunk_id"] for item in second])
        self.assertEqual(first[0]["article_no"], "第一条")
        self.assertEqual(first[0]["locator_json"]["unit_kind"], "article")
        self.assertEqual(first[0]["locator_json"]["title_path"], ["第一章 总则"])
        self.assertEqual(first[0]["locator_json"]["chunk_strategy_version"], CHUNK_STRATEGY_VERSION)

    def test_long_article_sliding_windows_keep_same_semantic_unit(self):
        text = "\n".join(
            [
                "中华人民共和国劳动法",
                "第一章 总则",
                "第一条 " + "劳动者享有平等就业和选择职业的权利。" * 15 + "（一）用工自由。（二）获得劳动报酬。",
                "第二条 劳动者适用范围。",
            ]
        )
        rows = chunk_text(
            text,
            90,
            20,
            "doc_random",
            doc_type="docx",
            document_meta={"source_fingerprint": "fingerprint_002", "title": "中华人民共和国劳动法"},
        )

        first_article_rows = [row for row in rows if row["article_no"] == "第一条"]
        self.assertGreater(len(first_article_rows), 1)
        semantic_unit_ids = {row["locator_json"]["semantic_unit_id"] for row in first_article_rows}
        self.assertEqual(len(semantic_unit_ids), 1)
        self.assertEqual(
            [row["locator_json"]["window_index"] for row in first_article_rows],
            list(range(len(first_article_rows))),
        )
        self.assertEqual(
            {row["locator_json"]["window_count"] for row in first_article_rows},
            {len(first_article_rows)},
        )

    def test_non_law_text_falls_back_to_generic_chunking(self):
        rows = chunk_text(
            "这是一份普通说明文档，用于测试通用切分回退逻辑。",
            40,
            10,
            "doc_generic",
            doc_type="text",
            document_meta={"source_fingerprint": "generic_fp", "title": "说明文"},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["locator_json"]["unit_kind"], "generic")
        self.assertIsNone(rows[0]["article_no"])


if __name__ == "__main__":
    unittest.main()
