"""Embedding 服务：支持 SiliconFlow API、SentenceTransformer 和 Hash fallback。"""

import logging
import threading
from typing import Any, List, Optional, Sequence

import httpx
import numpy as np

from .text_utils import l2_normalize_rows, tokenize

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover
    SentenceTransformer = None


class EmbeddingProvider:
    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError


class HashEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dim: int = 256):
        self.dim = dim

    @property
    def name(self) -> str:
        return f"hash-{self.dim}"

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        rows: List[np.ndarray] = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            for token in tokenize(text):
                slot = hash(token) % self.dim
                vec[slot] += 1.0
            rows.append(vec)
        matrix = np.stack(rows) if rows else np.zeros((0, self.dim), dtype=np.float32)
        return l2_normalize_rows(matrix)


class SiliconFlowEmbeddingProvider(EmbeddingProvider):
    """通过 SiliconFlow API 获取文本向量。"""

    BATCH_SIZE = 64  # API 单次最大输入数

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(timeout=60.0)

    @property
    def name(self) -> str:
        return f"siliconflow/{self.model}"

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        all_embeddings: List[List[float]] = []
        text_list = list(texts)
        for start in range(0, len(text_list), self.BATCH_SIZE):
            batch = text_list[start : start + self.BATCH_SIZE]
            resp = self._client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": batch, "encoding_format": "float"},
            )
            resp.raise_for_status()
            data = resp.json()
            # 按 index 排序，确保顺序一致
            items = sorted(data["data"], key=lambda x: x["index"])
            all_embeddings.extend([item["embedding"] for item in items])
        if len(all_embeddings) != len(text_list):
            logger.error(
                "SiliconFlow embeddings count mismatch: expected %d, got %d",
                len(text_list),
                len(all_embeddings),
            )
            raise RuntimeError("SiliconFlow embeddings count mismatch")
        matrix = np.array(all_embeddings, dtype=np.float32)
        return l2_normalize_rows(matrix)


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model: Optional[Any] = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.model_name

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if SentenceTransformer is None:
                raise RuntimeError("sentence-transformers 不可用")
            self._model = SentenceTransformer(self.model_name)
            return self._model

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        model = self._load_model()
        emb = model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        emb = np.asarray(emb, dtype=np.float32)
        return emb if emb.ndim == 2 else np.expand_dims(emb, axis=0)


class EmbeddingService:
    def __init__(self, model_name: str):
        self._lock = threading.Lock()
        self._provider: EmbeddingProvider = self._build_provider(model_name)

    def _fallback_to_hash(self, reason: Exception) -> EmbeddingProvider:
        with self._lock:
            if isinstance(self._provider, HashEmbeddingProvider):
                return self._provider
            logger.warning("embedding provider 失败，自动降级为 hash embedding: %s", reason)
            self._provider = HashEmbeddingProvider()
            return self._provider

    def _build_provider(self, model_name: str) -> EmbeddingProvider:
        from app.core.config import settings

        provider_type = (settings.EMBEDDING_PROVIDER or "").strip().lower()
        wanted = (model_name or "").strip()

        if provider_type in {"hash", "mock", "simple-local", "local-hash"}:
            return HashEmbeddingProvider()

        # SiliconFlow 在线 API
        if provider_type == "siliconflow":
            api_key = settings.SILICONFLOW_API_KEY
            if not api_key:
                logger.warning("SILICONFLOW_API_KEY 未设置，降级为 hash embedding")
                return HashEmbeddingProvider()
            logger.info("使用 SiliconFlow embedding: %s", settings.SILICONFLOW_EMBED_MODEL)
            return SiliconFlowEmbeddingProvider(
                api_key=api_key,
                base_url=settings.SILICONFLOW_BASE_URL,
                model=settings.SILICONFLOW_EMBED_MODEL,
            )

        if provider_type not in {"", "auto", "sentence-transformers", "local", "transformers"}:
            logger.warning("未知 EMBEDDING_PROVIDER=%s，降级为 hash embedding", settings.EMBEDDING_PROVIDER)
            return HashEmbeddingProvider()

        # 本地 hash / mock
        if wanted.lower() in {"", "simple-local", "hash", "mock"}:
            return HashEmbeddingProvider()

        # SentenceTransformer 本地模型
        try:
            return SentenceTransformerEmbeddingProvider(wanted)
        except Exception as exc:  # pragma: no cover
            logger.warning("加载 embedding 模型失败，降级为 hash embedding: %s", exc)
            return HashEmbeddingProvider()

    @property
    def name(self) -> str:
        return self._provider.name

    def set_model(self, model_name: str) -> bool:
        model_name = (model_name or "").strip()
        if not model_name:
            return False
        with self._lock:
            if model_name == self._provider.name:
                return False
            self._provider = self._build_provider(model_name)
            return True

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        try:
            return self._provider.embed_texts(texts)
        except Exception as exc:
            provider = self._fallback_to_hash(exc)
            return provider.embed_texts(texts)
