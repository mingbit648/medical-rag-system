import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.embedder import EmbeddingService, HashEmbeddingProvider
from app.core.retriever import rerank
from app.core.text_utils import ChunkRecord


class FailingProvider:
    @property
    def name(self) -> str:
        return "failing-provider"

    def embed_texts(self, texts):
        raise RuntimeError("remote embedding unavailable")


class EmbeddingFallbackTests(unittest.TestCase):
    def test_hash_provider_can_be_selected_explicitly(self):
        with patch.object(settings, "EMBEDDING_PROVIDER", "hash"):
            service = EmbeddingService("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

        self.assertIsInstance(service._provider, HashEmbeddingProvider)
        self.assertEqual(service.name, "hash-256")

    def test_service_falls_back_to_hash_when_provider_errors(self):
        service = object.__new__(EmbeddingService)
        service._lock = threading.Lock()
        service._provider = FailingProvider()

        matrix = service.embed_texts(["劳动合同", "工资"])

        self.assertIsInstance(service._provider, HashEmbeddingProvider)
        self.assertEqual(service.name, "hash-256")
        self.assertIsInstance(matrix, np.ndarray)
        self.assertEqual(matrix.shape[0], 2)
        self.assertEqual(matrix.shape[1], 256)

    def test_heuristic_rerank_skips_remote_and_local_rerankers(self):
        chunk = ChunkRecord(
            chunk_id="chk_1",
            doc_id="doc_1",
            chunk_index=0,
            chunk_text="劳动者有权获得劳动报酬。",
            start_pos=0,
            end_pos=13,
        )

        with patch.object(settings, "RERANK_PROVIDER", "heuristic"):
            with patch("app.core.retriever.siliconflow_rerank") as siliconflow_rerank:
                with patch("app.core.retriever.load_cross_encoder") as load_cross_encoder:
                    ranked = rerank(
                        query="劳动报酬",
                        query_tokens=["劳动", "报酬"],
                        fused=[{"chunk_id": "chk_1", "rrf": 0.8}],
                        bm25_ranked=[{"chunk_id": "chk_1", "score": 5.0}],
                        vector_ranked=[{"chunk_id": "chk_1", "score": 0.9}],
                        chunk_lookup={"chk_1": chunk},
                        chunk_terms={"chk_1": ["劳动", "报酬"]},
                        cross_encoder_state={"model": None, "disabled": False},
                        cross_encoder_model_name="cross-encoder/mock",
                    )

        siliconflow_rerank.assert_not_called()
        load_cross_encoder.assert_not_called()
        self.assertEqual(ranked[0]["chunk_id"], "chk_1")
        self.assertIsNone(ranked[0]["cross_encoder"])


if __name__ == "__main__":
    unittest.main()
