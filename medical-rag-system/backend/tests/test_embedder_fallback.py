import sys
import threading
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.embedder import EmbeddingService, HashEmbeddingProvider


class FailingProvider:
    @property
    def name(self) -> str:
        return "failing-provider"

    def embed_texts(self, texts):
        raise RuntimeError("remote embedding unavailable")


class EmbeddingFallbackTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
