"""
LegalRagService — 法律辅助咨询 RAG 引擎入口 (facade)。

所有子功能已拆分为独立模块：
  - text_utils   : 文本处理工具 + ChunkRecord
  - embedder     : EmbeddingService
  - doc_ingestion: 文档导入
  - chunker      : 文本分块
  - retriever    : BM25/向量检索 + RRF 融合 + Cross-Encoder 重排序
  - generator    : 引用构建 + LLM 调用 + prompt 组装

本文件仅保留 LegalRagService 类作为 facade 编排各模块。
外部 router 仍通过 `from app.core.rag_engine import engine` 调用。
"""

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from rank_bm25 import BM25Okapi

from app.core.config import settings
from app.repositories import PgRepository

from .text_utils import ChunkRecord, PRONOUN_REF_PATTERN, now_iso, tokenize
from .embedder import EmbeddingService
from .doc_ingestion import import_document
from .chunker import chunk_text
from .retriever import rank_bm25, rank_dense, rrf_fusion, rerank
from .generator import make_citation, generate_answer, generate_answer_stream

try:
    import chromadb
except Exception:  # pragma: no cover
    chromadb = None

logger = logging.getLogger(__name__)


class LegalRagService:
    def __init__(self, default_chunk_size: int = 800, default_chunk_overlap: int = 200):
        self.default_chunk_size = default_chunk_size
        self.default_chunk_overlap = default_chunk_overlap

        # 数据库：使用 PostgreSQL
        self.repo = PgRepository(settings.DATABASE_URL)

        self._lock = threading.RLock()
        self.chunk_lookup: Dict[str, ChunkRecord] = {}
        self.chunk_terms: Dict[str, List[str]] = {}
        self.doc_chunk_ids: Dict[str, List[str]] = {}

        self.bm25_enabled = True
        self.vector_enabled = True
        self.bm25_index: Optional[BM25Okapi] = None
        self.bm25_chunk_ids: List[str] = []

        self.embedding_service = EmbeddingService(settings.EMBED_MODEL_NAME)
        self.vector_chunk_ids: List[str] = []
        self.vector_matrix = np.zeros((0, 1), dtype=np.float32)

        self.chroma_client: Optional[Any] = None
        self.chroma_collection: Optional[Any] = None
        self._init_chroma()

        self.cross_encoder_model_name = settings.RERANK_MODEL_NAME
        self._cross_encoder_state: dict = {"model": None, "disabled": False}

        self._reload_index_cache()

    # ─── ChromaDB 初始化 ──────────────────────────────────
    def _init_chroma(self) -> None:
        backend = (settings.VECTOR_DB_BACKEND or "").strip().lower()
        if backend != "chroma":
            return
        if chromadb is None:
            logger.warning("chromadb 不可用，向量检索将使用内存回退")
            return
        data_root = Path(settings.DATA_DIR)
        persist_dir = Path(settings.CHROMA_PERSIST_DIR)
        if not persist_dir.is_absolute():
            if persist_dir.parts and persist_dir.parts[0] == data_root.name:
                persist_dir = persist_dir
            else:
                persist_dir = data_root / persist_dir
        try:
            persist_dir.mkdir(parents=True, exist_ok=True)
            self.chroma_client = chromadb.PersistentClient(path=str(persist_dir))
            self.chroma_collection = self.chroma_client.get_or_create_collection(
                name=settings.CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("chroma initialized: %s", persist_dir)
        except Exception as exc:
            logger.warning("初始化 Chroma 失败: %s", exc)
            self.chroma_client = None
            self.chroma_collection = None

    # ─── 索引缓存管理 ────────────────────────────────────
    def _reload_index_cache(self) -> None:
        with self._lock:
            self.chunk_lookup.clear()
            self.chunk_terms.clear()
            self.doc_chunk_ids.clear()
            for row in self.repo.list_chunks(indexed_only=True):
                chunk = ChunkRecord(
                    chunk_id=row["chunk_id"],
                    doc_id=row["doc_id"],
                    chunk_index=row["chunk_index"],
                    chunk_text=row["chunk_text"],
                    start_pos=row["start_pos"],
                    end_pos=row["end_pos"],
                    section=row.get("section"),
                    article_no=row.get("article_no"),
                    page_start=row.get("page_start"),
                    page_end=row.get("page_end"),
                )
                self.chunk_lookup[chunk.chunk_id] = chunk
                self.chunk_terms[chunk.chunk_id] = tokenize(chunk.chunk_text)
                self.doc_chunk_ids.setdefault(chunk.doc_id, []).append(chunk.chunk_id)
            self._rebuild_bm25_index()
            self._rebuild_vector_index()

    def _rebuild_bm25_index(self) -> None:
        if not self.bm25_enabled:
            self.bm25_index = None
            self.bm25_chunk_ids = []
            return
        chunk_ids = list(self.chunk_lookup.keys())
        if not chunk_ids:
            self.bm25_index = None
            self.bm25_chunk_ids = []
            return
        corpus_tokens = [self.chunk_terms.get(cid, []) for cid in chunk_ids]
        self.bm25_index = BM25Okapi(corpus_tokens)
        self.bm25_chunk_ids = chunk_ids

    def _clear_chroma(self) -> None:
        if self.chroma_collection is None:
            return
        try:
            existing = self.chroma_collection.get(include=[])
            ids = existing.get("ids", [])
            if ids:
                self.chroma_collection.delete(ids=ids)
        except Exception as exc:
            logger.warning("清空 Chroma 失败: %s", exc)

    def _rebuild_vector_index(self) -> None:
        if not self.vector_enabled:
            self.vector_chunk_ids = []
            self.vector_matrix = np.zeros((0, 1), dtype=np.float32)
            self._clear_chroma()
            return
        chunk_ids = list(self.chunk_lookup.keys())
        if not chunk_ids:
            self.vector_chunk_ids = []
            self.vector_matrix = np.zeros((0, 1), dtype=np.float32)
            self._clear_chroma()
            return
        from .text_utils import l2_normalize_rows
        texts = [self.chunk_lookup[cid].chunk_text for cid in chunk_ids]
        embeddings = self.embedding_service.embed_texts(texts)
        embeddings = np.asarray(embeddings, dtype=np.float32)
        embeddings = l2_normalize_rows(embeddings)
        self.vector_chunk_ids = chunk_ids
        self.vector_matrix = embeddings
        if self.chroma_collection is None:
            return
        try:
            self._clear_chroma()
            metadatas = []
            for cid in chunk_ids:
                chunk = self.chunk_lookup[cid]
                metadatas.append({
                    "doc_id": chunk.doc_id,
                    "chunk_index": chunk.chunk_index,
                    "section": chunk.section or "",
                    "article_no": chunk.article_no or "",
                })
            self.chroma_collection.upsert(
                ids=chunk_ids,
                documents=texts,
                embeddings=embeddings.tolist(),
                metadatas=metadatas,
            )
        except Exception as exc:
            logger.warning("Chroma upsert 失败: %s", exc)

    # ─── 文档管理 (委托) ─────────────────────────────────
    def import_document(self, file_name: str, content: bytes, doc_type=None, source_url=None):
        return import_document(self.repo, file_name, content, doc_type, source_url)

    def build_index(self, doc_id, chunk_size=None, overlap=None, bm25_enabled=True, vector_enabled=True, embed_model=None):
        doc = self.repo.get_document(doc_id)
        if doc is None:
            raise KeyError("文档不存在")
        c_size = chunk_size or self.default_chunk_size
        c_overlap = self.default_chunk_overlap if overlap is None else overlap
        chunk_rows = chunk_text(doc["text"], c_size, c_overlap, doc_id)
        self.repo.replace_chunks(doc_id, chunk_rows)
        self.repo.update_document_index_status(doc_id, parse_status="indexed", chunks=len(chunk_rows))
        self.bm25_enabled = bm25_enabled
        self.vector_enabled = vector_enabled
        if embed_model:
            self.embedding_service.set_model(embed_model)
        self._reload_index_cache()
        return {
            "doc_id": doc_id, "status": "indexed", "chunks": len(chunk_rows),
            "chunk": {"size": c_size, "overlap": c_overlap},
            "bm25": {"enabled": self.bm25_enabled},
            "vector": {"enabled": self.vector_enabled, "embed_model": self.embedding_service.name},
        }

    def get_doc_status(self, doc_id):
        doc = self.repo.get_document(doc_id)
        if doc is None:
            raise KeyError("文档不存在")
        return {"doc_id": doc["doc_id"], "title": doc["title"], "doc_type": doc["doc_type"],
                "parse_status": doc["parse_status"], "chunks": doc.get("chunks", 0), "created_at": doc["created_at"]}

    def list_docs(self):
        docs = self.repo.list_documents()
        return [{"doc_id": d["doc_id"], "title": d["title"], "doc_type": d["doc_type"],
                 "parse_status": d["parse_status"], "chunks": d.get("chunks", 0), "created_at": d["created_at"]} for d in docs]

    # ─── 检索 + 生成 ────────────────────────────────────
    def retrieve(self, query, bm25_topn=50, vector_topn=50, fusion_k=60,
                 rerank_topk=30, rerank_topm=8, save_citations=True,
                 llm=None, history_messages=None, user_query_for_answer=None, generate_answer_flag=True):
        chunks = self._indexed_chunks()
        if not chunks:
            raise ValueError("尚无已建索引文档，请先导入并建立索引。")
        query_tokens = tokenize(query)
        if not query_tokens:
            raise ValueError("查询内容为空或不可解析。")

        bm25_ranked = rank_bm25(query_tokens, bm25_topn, self.bm25_enabled, self.bm25_index, self.bm25_chunk_ids)
        vector_ranked = rank_dense(query, vector_topn, self.vector_enabled, self.embedding_service,
                                   self.vector_chunk_ids, self.vector_matrix, self.chroma_collection)
        fused = rrf_fusion(bm25_ranked, vector_ranked, fusion_k)[:max(1, rerank_topk)]
        reranked = rerank(query, query_tokens, fused, bm25_ranked, vector_ranked,
                          self.chunk_lookup, self.chunk_terms, self._cross_encoder_state, self.cross_encoder_model_name)
                          
        # FR-15: 可引用性阈值过滤
        evidence = [hit for hit in reranked[:max(1, rerank_topm)] if hit.get("rerank", 0.0) > 0.05]

        citations = [make_citation(self.repo, hit, persist=save_citations) for hit in evidence] if save_citations else []
        answer = ""
        if generate_answer_flag:
            answer = generate_answer(
                query=user_query_for_answer or query,
                citation_like=citations if save_citations else evidence,
                llm=llm or {},
                history_messages=history_messages or [],
            )
        return {"answer_md": answer, "citations": citations,
                "debug": {"bm25": bm25_ranked, "vector": vector_ranked, "fusion": fused, "rerank": reranked}}

    async def retrieve_stream(self, query, bm25_topn=50, vector_topn=50, fusion_k=60,
                 rerank_topk=30, rerank_topm=8, save_citations=True,
                 llm=None, history_messages=None, user_query_for_answer=None):
        chunks = self._indexed_chunks()
        if not chunks:
            raise ValueError("尚无已建索引文档，请先导入并建立索引。")
        query_tokens = tokenize(query)
        if not query_tokens:
            raise ValueError("查询内容为空或不可解析。")

        bm25_ranked = rank_bm25(query_tokens, bm25_topn, self.bm25_enabled, self.bm25_index, self.bm25_chunk_ids)
        vector_ranked = rank_dense(query, vector_topn, self.vector_enabled, self.embedding_service,
                                   self.vector_chunk_ids, self.vector_matrix, self.chroma_collection)
        fused = rrf_fusion(bm25_ranked, vector_ranked, fusion_k)[:max(1, rerank_topk)]
        reranked = rerank(query, query_tokens, fused, bm25_ranked, vector_ranked,
                          self.chunk_lookup, self.chunk_terms, self._cross_encoder_state, self.cross_encoder_model_name)
        
        # FR-15: 可引用性阈值过滤 (过滤掉 rerank_score <= 0.2 或相关度极低的切片)
        evidence = [hit for hit in reranked[:max(1, rerank_topm)] if hit.get("rerank", 0.0) > 0.05]

        citations = [make_citation(self.repo, hit, persist=save_citations) for hit in evidence] if save_citations else []
        
        # 产生第一条消息作为前置 metadata
        yield {"type": "metadata", "citations": citations, 
               "debug": {"bm25": bm25_ranked, "vector": vector_ranked, "fusion": fused, "rerank": reranked}}
        
        # 产生文本 chunk
        async for chunk in generate_answer_stream(
            query=user_query_for_answer or query,
            citation_like=citations if save_citations else evidence,
            llm=llm or {},
            history_messages=history_messages or [],
        ):
            yield {"type": "chunk", "content": chunk}


    def chat(self, session_id, query, topn, fusion, rerank, llm):
        sid = session_id or f"s_{uuid.uuid4().hex[:12]}"
        history = self.repo.list_messages(session_id=sid, limit=settings.HISTORY_WINDOW_MESSAGES)
        retrieval_query = self._compose_retrieval_query(query, history)
        result = self.retrieve(
            query=retrieval_query,
            bm25_topn=topn.get("bm25", settings.TOPN_BM25),
            vector_topn=topn.get("vector", settings.TOPN_VECTOR),
            fusion_k=fusion.get("k", settings.FUSION_K),
            rerank_topk=rerank.get("topk", settings.RERANK_TOPK),
            rerank_topm=rerank.get("topm", settings.RERANK_TOPM),
            save_citations=True, llm=llm, history_messages=history,
            user_query_for_answer=query, generate_answer_flag=True,
        )
        self.repo.append_message(f"msg_{uuid.uuid4().hex[:16]}", sid, "user", query, now_iso())
        self.repo.append_message(f"msg_{uuid.uuid4().hex[:16]}", sid, "assistant", result["answer_md"], now_iso())
        result["debug"]["retrieval_query"] = retrieval_query
        return {"session_id": sid, "answer_md": result["answer_md"], "citations": result["citations"], "debug": result["debug"]}

    async def chat_stream(self, session_id, query, topn, fusion, rerank, llm):
        sid = session_id or f"s_{uuid.uuid4().hex[:12]}"
        history = self.repo.list_messages(session_id=sid, limit=settings.HISTORY_WINDOW_MESSAGES)
        retrieval_query = self._compose_retrieval_query(query, history)
        
        self.repo.append_message(f"msg_{uuid.uuid4().hex[:16]}", sid, "user", query, now_iso())
        
        full_answer = []
        citations = []
        debug_info = {}
        
        async for item in self.retrieve_stream(
            query=retrieval_query,
            bm25_topn=topn.get("bm25", settings.TOPN_BM25),
            vector_topn=topn.get("vector", settings.TOPN_VECTOR),
            fusion_k=fusion.get("k", settings.FUSION_K),
            rerank_topk=rerank.get("topk", settings.RERANK_TOPK),
            rerank_topm=rerank.get("topm", settings.RERANK_TOPM),
            save_citations=True, llm=llm, history_messages=history,
            user_query_for_answer=query
        ):
            if getattr(item, "get", None) and item.get("type") == "metadata":
                citations = item.get("citations", [])
                debug_info = item.get("debug", {})
                debug_info["retrieval_query"] = retrieval_query
                yield {"type": "metadata", "session_id": sid, "citations": citations, "debug": debug_info}
            elif getattr(item, "get", None) and item.get("type") == "chunk":
                chunk_str = item.get("content", "")
                full_answer.append(chunk_str)
                yield {"type": "chunk", "content": chunk_str}
                
        # 保存完整答案
        final_answer_md = "".join(full_answer)
        self.repo.append_message(f"msg_{uuid.uuid4().hex[:16]}", sid, "assistant", final_answer_md, now_iso())

    def _compose_retrieval_query(self, query, history):
        if not settings.ENABLE_HISTORY_FOR_RETRIEVAL or not history:
            return query
        user_messages = [m.get("content", "") for m in history if m.get("role") == "user" and m.get("content")]
        if not user_messages:
            return query
        previous = user_messages[-1].strip()
        if not previous:
            return query
        if len(query) <= 20 or PRONOUN_REF_PATTERN.search(query):
            return f"{previous}\n{query}"
        return query

    def get_session_history(self, session_id, limit=50):
        return {"session_id": session_id, "messages": self.repo.list_messages(session_id=session_id, limit=limit)}

    def get_citation_view(self, citation_id, context_before, context_after):
        citation = self.repo.get_citation(citation_id)
        if citation is None:
            raise KeyError("引用不存在")
        payload = citation["payload"]
        chunk = self.chunk_lookup.get(citation["chunk_id"])
        doc = self.repo.get_document(citation["doc_id"])
        if chunk is None or doc is None:
            return {
                "doc_id": citation["doc_id"], "doc_type": "unknown",
                "context_text": payload.get("snippet", ""),
                "highlight": {"method": "whole_chunk", "chunk_text": payload.get("snippet", ""), "reason": "chunk_not_found"},
                "fallback": {"reason": "chunk_or_doc_missing"},
            }
        full_text = doc.get("text", "")
        start = max(0, chunk.start_pos - context_before)
        end = min(len(full_text), chunk.end_pos + context_after)
        context_text = full_text[start:end]
        local_start = max(0, chunk.start_pos - start)
        local_end = max(local_start, min(len(context_text), chunk.end_pos - start))
        return {
            "doc_id": doc["doc_id"], "doc_type": doc["doc_type"],
            "context_text": context_text,
            "highlight": {"method": "offset", "start": local_start, "end": local_end},
            "fallback": None,
        }

    # ─── 实验评测 ────────────────────────────────────────
    def run_experiment(self, dataset, topn, fusion, rerank):
        if not dataset:
            raise ValueError("实验数据集不能为空。")
        case_results = []
        baseline_recall = baseline_mrr = improved_recall = improved_mrr = 0.0
        for case in dataset:
            query = case["query"]
            relevant_chunk_ids = set(case.get("relevant_chunk_ids", []))
            relevant_doc_ids = set(case.get("relevant_doc_ids", []))
            if not relevant_chunk_ids and not relevant_doc_ids:
                raise ValueError("每个实验样本至少需要 relevant_chunk_ids 或 relevant_doc_ids。")
            dense_ranked = rank_dense(query, 5, self.vector_enabled, self.embedding_service,
                                     self.vector_chunk_ids, self.vector_matrix, self.chroma_collection)
            baseline_top5 = [x["chunk_id"] for x in dense_ranked[:5]]
            debug = self.retrieve(
                query=query,
                bm25_topn=topn.get("bm25", settings.TOPN_BM25),
                vector_topn=topn.get("vector", settings.TOPN_VECTOR),
                fusion_k=fusion.get("k", settings.FUSION_K),
                rerank_topk=rerank.get("topk", settings.RERANK_TOPK),
                rerank_topm=max(5, rerank.get("topm", settings.RERANK_TOPM)),
                save_citations=False, generate_answer_flag=False,
            )["debug"]
            improved_top5 = [x["chunk_id"] for x in debug["rerank"][:5]]
            b_recall, b_mrr = self._calc_recall_mrr(baseline_top5, relevant_chunk_ids, relevant_doc_ids)
            i_recall, i_mrr = self._calc_recall_mrr(improved_top5, relevant_chunk_ids, relevant_doc_ids)
            baseline_recall += b_recall; baseline_mrr += b_mrr
            improved_recall += i_recall; improved_mrr += i_mrr
            case_results.append({
                "query": query, "baseline_top5": baseline_top5, "improved_top5": improved_top5,
                "baseline_recall@5": b_recall, "baseline_mrr": b_mrr,
                "improved_recall@5": i_recall, "improved_mrr": i_mrr,
            })
        total = len(dataset)
        metrics = {
            "baseline": {"recall@5": round(baseline_recall/total, 4), "mrr": round(baseline_mrr/total, 4)},
            "improved": {"recall@5": round(improved_recall/total, 4), "mrr": round(improved_mrr/total, 4)},
            "total_cases": total, "cases": case_results,
        }
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.repo.save_run(run_id, "baseline_vs_hybrid_rerank", {"topn": topn, "fusion": fusion, "rerank": rerank}, metrics, now_iso())
        return {"run_id": run_id, "mode": "baseline_vs_hybrid_rerank", "metrics": metrics}

    def get_run(self, run_id):
        run = self.repo.get_run(run_id)
        if run is None:
            raise KeyError("实验运行记录不存在")
        return {"run_id": run["run_id"], "mode": run["mode"], "config": run["config"],
                "metrics": run["metrics"], "created_at": run["created_at"]}

    def list_runs(self, limit=20):
        items = self.repo.list_runs(limit=limit)
        return {"items": [{"run_id": i["run_id"], "mode": i["mode"], "config": i["config"],
                           "metrics": i["metrics"], "created_at": i["created_at"]} for i in items]}

    def _calc_recall_mrr(self, ranking_ids, relevant_chunk_ids, relevant_doc_ids):
        recall = mrr = 0.0
        for idx, chunk_id in enumerate(ranking_ids, start=1):
            chunk = self.chunk_lookup.get(chunk_id)
            if chunk is None:
                continue
            hit = (chunk_id in relevant_chunk_ids) or (chunk.doc_id in relevant_doc_ids)
            if hit and recall == 0.0:
                recall = 1.0
                mrr = 1.0 / idx
                break
        return recall, mrr

    def _indexed_chunks(self):
        with self._lock:
            return list(self.chunk_lookup.values())


# ─── 全局引擎实例（router 通过 from app.core.rag_engine import engine 使用）
engine = LegalRagService(default_chunk_size=settings.CHUNK_SIZE, default_chunk_overlap=settings.CHUNK_OVERLAP)

