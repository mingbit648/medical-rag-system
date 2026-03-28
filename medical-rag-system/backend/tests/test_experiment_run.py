import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.rag_engine import LegalRagService
from app.core.text_utils import ChunkRecord


class FakeExperimentRepo:
    def __init__(self):
        self.saved_run = None
        self.kb = {"kb_id": "kb_experiment", "name": "实验知识库"}
        self.docs = [
            {
                "doc_id": "doc_law",
                "title": "中华人民共和国劳动法",
                "parse_status": "indexed",
                "source_fingerprint": "fp_doc_law",
                "chunk_strategy_version": "law_structured_v1",
            }
        ]

    def get_knowledge_base(self, kb_id):
        if kb_id != self.kb["kb_id"]:
            return None
        return self.kb

    def list_documents(self, *, include_text=True, kb_id=None):
        if kb_id and kb_id != self.kb["kb_id"]:
            return []
        return list(self.docs)

    def save_run(self, run_id, kb_id, mode, config, metrics, created_at):
        self.saved_run = {
            "run_id": run_id,
            "kb_id": kb_id,
            "mode": mode,
            "config": config,
            "metrics": metrics,
            "created_at": created_at,
        }


class ExperimentRunTests(unittest.TestCase):
    def _make_service(self):
        service = object.__new__(LegalRagService)
        service.repo = FakeExperimentRepo()
        service.chunk_lookup = {
            "chk_bm": ChunkRecord(
                chunk_id="chk_bm",
                doc_id="doc_law",
                chunk_index=0,
                chunk_text="第一条 劳动者享有平等就业和选择职业的权利。",
                start_pos=0,
                end_pos=20,
                article_no="第一条",
            ),
            "chk_vec": ChunkRecord(
                chunk_id="chk_vec",
                doc_id="doc_law",
                chunk_index=1,
                chunk_text="第二条 用人单位应当依法支付劳动报酬。",
                start_pos=21,
                end_pos=40,
                article_no="第二条",
            ),
        }
        service.chunk_terms = {
            "chk_bm": ["第一条", "平等就业"],
            "chk_vec": ["第二条", "劳动报酬"],
        }
        service.doc_chunk_ids = {"doc_law": ["chk_bm", "chk_vec"]}
        service.kb_chunk_ids = {"kb_experiment": ["chk_bm", "chk_vec"]}
        service.bm25_enabled = True
        service.vector_enabled = True
        service.bm25_index = object()
        service.bm25_chunk_ids = ["chk_bm", "chk_vec"]
        service.embedding_service = type("Embedding", (), {"name": "hash-256"})()
        service.vector_chunk_ids = ["chk_vec", "chk_bm"]
        service.vector_matrix = np.ones((2, 1), dtype=np.float32)
        service.vector_chunk_index = {"chk_vec": 0, "chk_bm": 1}
        service.chroma_collection = None
        service._cross_encoder_state = {"model": None, "disabled": False}
        service.cross_encoder_model_name = "cross-encoder/mock"
        return service

    @patch(
        "app.core.rag_engine.rerank",
        return_value=[
            {"chunk_id": "chk_vec", "rerank": 0.95},
            {"chunk_id": "chk_bm", "rerank": 0.45},
        ],
    )
    @patch(
        "app.core.rag_engine.rrf_fusion",
        return_value=[
            {"chunk_id": "chk_bm", "rrf": 0.8},
            {"chunk_id": "chk_vec", "rrf": 0.7},
        ],
    )
    @patch(
        "app.core.rag_engine.rank_dense",
        return_value=[
            {"chunk_id": "chk_vec", "score": 0.91},
            {"chunk_id": "chk_bm", "score": 0.35},
        ],
    )
    @patch(
        "app.core.rag_engine.rank_bm25",
        return_value=[
            {"chunk_id": "chk_bm", "score": 9.0},
            {"chunk_id": "chk_vec", "score": 3.0},
        ],
    )
    def test_run_experiment_returns_four_groups_and_persists_versions(self, *_):
        service = self._make_service()

        result = service.run_experiment(
            kb_id="kb_experiment",
            dataset=[
                {
                    "case_id": "case_01",
                    "query": "公司拖欠工资怎么办？",
                    "relevant_chunk_ids": ["chk_vec"],
                    "relevant_doc_ids": [],
                }
            ],
            dataset_version="dataset_v_test",
            topn={"bm25": 50, "vector": 50},
            fusion={"method": "rrf", "k": 60},
            rerank={"topk": 30, "topm": 8},
        )

        self.assertEqual(result["config"]["dataset_version"], "dataset_v_test")
        self.assertIn("groups", result["metrics"])
        self.assertEqual(
            sorted(result["metrics"]["groups"].keys()),
            ["bm25_only", "hybrid_no_rerank", "hybrid_rerank", "vector_only"],
        )
        self.assertEqual(result["metrics"]["baseline"], result["metrics"]["groups"]["vector_only"])
        self.assertEqual(result["metrics"]["improved"], result["metrics"]["groups"]["hybrid_rerank"])
        self.assertEqual(result["metrics"]["groups"]["hybrid_rerank"]["mrr"], 1.0)
        self.assertAlmostEqual(result["metrics"]["groups"]["bm25_only"]["mrr"], 0.5, places=4)
        self.assertIsNotNone(service.repo.saved_run)
        self.assertEqual(service.repo.saved_run["kb_id"], "kb_experiment")
        self.assertEqual(service.repo.saved_run["config"]["corpus_version"], result["config"]["corpus_version"])

    def test_evaluate_experiment_group_falls_back_to_doc_labels(self):
        service = self._make_service()
        entries = [
            {
                "rank": 1,
                "chunk_id": "chk_bm",
                "doc_id": "doc_law",
                "matched_relevant_chunk": False,
                "matched_relevant_doc": False,
                "scores": {},
            }
        ]

        metrics = service._evaluate_experiment_group(
            entries,
            relevant_chunk_ids=set(),
            relevant_doc_ids={"doc_law"},
        )

        self.assertEqual(metrics["hit@5"], 1.0)
        self.assertEqual(metrics["mrr"], 1.0)
        self.assertTrue(entries[0]["matched_relevant_doc"])


if __name__ == "__main__":
    unittest.main()
