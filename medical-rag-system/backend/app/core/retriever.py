"""检索模块：BM25、向量检索、RRF 融合、Cross-Encoder / SiliconFlow 重排序。"""

import logging
from typing import Any, Dict, List, Optional, Set

import httpx
import numpy as np
from rank_bm25 import BM25Okapi

from app.core.config import settings
from .text_utils import ChunkRecord, l2_normalize_rows, tokenize

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import CrossEncoder
except Exception:  # pragma: no cover
    CrossEncoder = None


def rank_bm25(
    query_tokens: List[str],
    topn: int,
    bm25_enabled: bool,
    bm25_index: Optional[BM25Okapi],
    bm25_chunk_ids: List[str],
) -> List[Dict[str, Any]]:
    if not query_tokens or topn <= 0 or not bm25_enabled or bm25_index is None:
        return []
    scores = bm25_index.get_scores(query_tokens)
    ranked = []
    for chunk_id, score in zip(bm25_chunk_ids, scores):
        score = float(score)
        if score > 0:
            ranked.append({"chunk_id": chunk_id, "score": score})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:topn]


def rank_dense(
    query: str,
    topn: int,
    vector_enabled: bool,
    embedding_service,
    vector_chunk_ids: List[str],
    vector_matrix: np.ndarray,
    chroma_collection: Optional[Any],
) -> List[Dict[str, Any]]:
    if topn <= 0 or not vector_enabled:
        return []
    if len(vector_chunk_ids) == 0:
        return []

    query_embedding = embedding_service.embed_texts([query])
    if query_embedding.size == 0:
        return []
    query_vec = query_embedding[0]

    if chroma_collection is not None:
        try:
            n_results = min(topn, len(vector_chunk_ids))
            result = chroma_collection.query(
                query_embeddings=[query_vec.tolist()],
                n_results=n_results,
                include=["distances"],
            )
            ids = result.get("ids", [[]])[0]
            distances = result.get("distances", [[]])[0]
            ranked = []
            for chunk_id, distance in zip(ids, distances):
                sim = 1.0 - float(distance)
                ranked.append({"chunk_id": chunk_id, "score": sim})
            ranked.sort(key=lambda item: item["score"], reverse=True)
            return ranked[:topn]
        except Exception as exc:  # pragma: no cover
            logger.warning("Chroma query 失败，回退内存向量检索: %s", exc)

    query_norm = query_vec / max(1e-8, float(np.linalg.norm(query_vec)))
    sims = vector_matrix @ query_norm
    ranked = []
    for idx, sim in enumerate(sims.tolist()):
        ranked.append({"chunk_id": vector_chunk_ids[idx], "score": float(sim)})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:topn]


def rrf_fusion(bm25_ranked: List[Dict[str, Any]], vector_ranked: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    score_map: Dict[str, float] = {}
    for ranked in (bm25_ranked, vector_ranked):
        for idx, item in enumerate(ranked, start=1):
            score_map[item["chunk_id"]] = score_map.get(item["chunk_id"], 0.0) + 1.0 / (k + idx)
    fused = [{"chunk_id": chunk_id, "rrf": score} for chunk_id, score in score_map.items()]
    fused.sort(key=lambda item: item["rrf"], reverse=True)
    return fused


def load_cross_encoder(model_name: str, device: str, state: dict) -> Optional[Any]:
    """加载或返回已缓存的 CrossEncoder。state 是一个可变容器 dict。"""
    if state.get("disabled"):
        return None
    if state.get("model") is not None:
        return state["model"]
    if CrossEncoder is None:
        state["disabled"] = True
        logger.warning("CrossEncoder 不可用，回退启发式 rerank")
        return None
    try:
        state["model"] = CrossEncoder(model_name, device=device)
        return state["model"]
    except Exception as exc:  # pragma: no cover
        state["disabled"] = True
        logger.warning("加载 CrossEncoder 失败，回退启发式 rerank: %s", exc)
        return None


def score_cross_encoder(query: str, candidates: List[ChunkRecord], encoder) -> List[float]:
    if not candidates or encoder is None:
        return []
    pairs = [(query, chunk.chunk_text) for chunk in candidates]
    try:
        scores = encoder.predict(pairs, show_progress_bar=False)
        scores = np.asarray(scores, dtype=np.float32).reshape(-1)
        return [float(x) for x in scores.tolist()]
    except Exception as exc:  # pragma: no cover
        logger.warning("CrossEncoder rerank 失败，回退启发式 rerank: %s", exc)
        return []


def siliconflow_rerank(
    query: str,
    candidates: List[ChunkRecord],
    api_key: str,
    base_url: str,
    model: str,
    top_n: int = 30,
) -> List[float]:
    """调用 SiliconFlow rerank API，返回与 candidates 对齐的分数列表。"""
    if not candidates or not api_key:
        return []
    documents = [chunk.chunk_text for chunk in candidates]
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{base_url.rstrip('/')}/rerank",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "query": query,
                    "documents": documents,
                    "top_n": min(top_n, len(documents)),
                    "return_documents": False,
                },
            )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        # 构建 index -> score 映射
        score_map: Dict[int, float] = {}
        for item in results:
            score_map[item["index"]] = float(item["relevance_score"])
        # 按 candidates 原始顺序返回分数，未返回的设为 0
        return [score_map.get(i, 0.0) for i in range(len(candidates))]
    except Exception as exc:
        logger.warning("SiliconFlow rerank 失败，回退启发式 rerank: %s", exc)
        return []


def rerank(
    query: str,
    query_tokens: List[str],
    fused: List[Dict[str, Any]],
    bm25_ranked: List[Dict[str, Any]],
    vector_ranked: List[Dict[str, Any]],
    chunk_lookup: Dict[str, ChunkRecord],
    chunk_terms: Dict[str, List[str]],
    cross_encoder_state: dict,
    cross_encoder_model_name: str,
) -> List[Dict[str, Any]]:
    bm25_map = {item["chunk_id"]: item["score"] for item in bm25_ranked}
    vector_map = {item["chunk_id"]: item["score"] for item in vector_ranked}
    bm25_max = max([item["score"] for item in bm25_ranked], default=1.0)
    candidates = [chunk_lookup[item["chunk_id"]] for item in fused if item["chunk_id"] in chunk_lookup]

    # 根据 RERANK_PROVIDER 选择重排序方式
    rerank_provider = (settings.RERANK_PROVIDER or "").strip().lower()
    cross_scores: List[float] = []

    if rerank_provider == "siliconflow" and settings.SILICONFLOW_API_KEY:
        cross_scores = siliconflow_rerank(
            query=query,
            candidates=candidates,
            api_key=settings.SILICONFLOW_API_KEY,
            base_url=settings.SILICONFLOW_BASE_URL,
            model=settings.SILICONFLOW_RERANK_MODEL,
            top_n=len(candidates),
        )
    else:
        encoder = load_cross_encoder(cross_encoder_model_name, settings.CROSS_ENCODER_DEVICE, cross_encoder_state)
        cross_scores = score_cross_encoder(query, candidates, encoder)

    has_cross_scores = len(cross_scores) == len(candidates) and len(candidates) > 0

    ranked = []
    qset = set(query_tokens)
    for idx, item in enumerate(fused):
        chunk = chunk_lookup.get(item["chunk_id"])
        if chunk is None:
            continue
        overlap = len(qset & set(chunk_terms.get(chunk.chunk_id, []))) / max(1, len(qset))
        bm25_norm = min(1.0, bm25_map.get(chunk.chunk_id, 0.0) / max(1e-8, bm25_max))
        vector_score = vector_map.get(chunk.chunk_id, 0.0)
        heuristic_score = 0.45 * overlap + 0.35 * vector_score + 0.20 * bm25_norm

        cross_score = None
        if has_cross_scores:
            cross_score = cross_scores[idx]
            rerank_score = 0.9 * cross_score + 0.1 * heuristic_score
        else:
            rerank_score = heuristic_score

        ranked.append(
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "chunk_text": chunk.chunk_text,
                "rrf": item["rrf"],
                "bm25": bm25_map.get(chunk.chunk_id, 0.0),
                "vector": vector_map.get(chunk.chunk_id, 0.0),
                "cross_encoder": cross_score,
                "rerank": rerank_score,
                "section": chunk.section,
                "article_no": chunk.article_no,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
            }
        )
    ranked.sort(key=lambda item: item["rerank"], reverse=True)
    return ranked
