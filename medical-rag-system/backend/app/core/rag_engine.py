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

import hashlib
import json
import logging
import mimetypes
import shutil
import threading
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from rank_bm25 import BM25Okapi

from app.core.config import settings
from app.repositories import PgRepository
from app.services import SessionService

from .text_utils import ChunkRecord, PRONOUN_REF_PATTERN, now_iso, tokenize
from .embedder import EmbeddingService
from .doc_ingestion import import_document
from .chunker import CHUNK_STRATEGY_VERSION, chunk_text
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
        self.session_service = SessionService(self.repo)

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

    def _data_root(self) -> Path:
        return Path(settings.DATA_DIR)

    def _resolve_doc_file_path(self, doc: Dict[str, Any]) -> Optional[Path]:
        relative_path = (doc.get("file_path") or "").strip()
        if not relative_path:
            return None
        path = Path(relative_path)
        return path if path.is_absolute() else self._data_root() / path

    def _compute_source_fingerprint(self, doc: Dict[str, Any]) -> str:
        file_path = self._resolve_doc_file_path(doc)
        if file_path is not None and file_path.exists():
            try:
                return hashlib.sha1(file_path.read_bytes()).hexdigest()
            except OSError as exc:
                logger.warning("读取原始文件指纹失败，回退到文本指纹: %s", exc)

        text = doc.get("text") or ""
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _ensure_original_viewable(self, doc: Dict[str, Any]) -> Path:
        if doc.get("source_version") != 2 or not doc.get("has_original_file"):
            raise ValueError("该文档需重新上传并重建索引后才能直达原文。")
        file_path = self._resolve_doc_file_path(doc)
        if file_path is None or not file_path.exists():
            raise ValueError("原始文档文件不存在，请重新上传并重建索引。")
        return file_path

    @staticmethod
    def _normalize_highlight_range(text: str, start_pos: int, end_pos: int) -> Dict[str, int]:
        text_length = len(text)
        start = max(0, min(int(start_pos), text_length))
        end = max(start, min(int(end_pos), text_length))
        return {"start": start, "end": end}

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
                    locator_json=row.get("locator_json") or {},
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
        try:
            embeddings = self.embedding_service.embed_texts(texts)
        except Exception as exc:
            logger.warning("rebuild vector index failed, fallback to empty vector index: %s", exc)
            self.vector_chunk_ids = []
            self.vector_matrix = np.zeros((0, 1), dtype=np.float32)
            self._clear_chroma()
            return
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
        document_meta = {**(doc.get("meta_json") or {})}
        document_meta["source_fingerprint"] = document_meta.get("source_fingerprint") or self._compute_source_fingerprint(doc)
        document_meta["title"] = doc.get("title")
        chunk_rows = chunk_text(
            doc["text"],
            c_size,
            c_overlap,
            doc_id,
            doc_type=doc["doc_type"],
            document_meta=document_meta,
        )
        self.repo.replace_chunks(doc_id, chunk_rows)
        semantic_chunking_enabled = any((row.get("locator_json") or {}).get("unit_kind") == "article" for row in chunk_rows)
        self.repo.update_document_index_status(
            doc_id,
            parse_status="indexed",
            chunks=len(chunk_rows),
            meta_updates={
                "source_fingerprint": document_meta["source_fingerprint"],
                "chunk_strategy_version": CHUNK_STRATEGY_VERSION,
                "semantic_chunking_enabled": semantic_chunking_enabled,
            },
        )
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
        doc = self.repo.get_document(doc_id, include_text=False)
        if doc is None:
            raise KeyError("文档不存在")
        return {"doc_id": doc["doc_id"], "title": doc["title"], "doc_type": doc["doc_type"],
                "parse_status": doc["parse_status"], "chunks": doc.get("chunks", 0), "created_at": doc["created_at"]}

    def list_docs(self):
        docs = self.repo.list_documents(include_text=False)
        return [{"doc_id": d["doc_id"], "title": d["title"], "doc_type": d["doc_type"],
                 "parse_status": d["parse_status"], "chunks": d.get("chunks", 0), "created_at": d["created_at"]} for d in docs]

    def delete_document(self, doc_id: str) -> bool:
        """删除文档及其关联数据，并重建索引缓存。"""
        doc = self.repo.get_document(doc_id, include_text=False)
        if doc is None:
            raise KeyError("文档不存在")
        file_path = self._resolve_doc_file_path(doc)
        deleted = self.repo.delete_document(doc_id)
        if deleted:
            upload_dir = (self._data_root() / "uploads" / doc_id)
            if upload_dir.exists():
                shutil.rmtree(upload_dir, ignore_errors=True)
            elif file_path and file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    logger.warning("删除原始文件失败: %s", file_path)
            self._reload_index_cache()
        return deleted

    # ─── 检索 + 生成 ────────────────────────────────────
    def retrieve(self, query, bm25_topn=50, vector_topn=50, fusion_k=60,
                 rerank_topk=30, rerank_topm=8, save_citations=True,
                 llm=None, history_messages=None, summary_text="",
                 user_query_for_answer=None, generate_answer_flag=True,
                 assistant_message_id=None):
        chunks = self._indexed_chunks()
        query_tokens = tokenize(query)
        if not query_tokens:
            raise ValueError("查询内容为空或不可解析。")

        if chunks:
            bm25_ranked = rank_bm25(query_tokens, bm25_topn, self.bm25_enabled, self.bm25_index, self.bm25_chunk_ids)
            vector_ranked = rank_dense(query, vector_topn, self.vector_enabled, self.embedding_service,
                                       self.vector_chunk_ids, self.vector_matrix, self.chroma_collection)
            fused = rrf_fusion(bm25_ranked, vector_ranked, fusion_k)[:max(1, rerank_topk)]
            reranked = rerank(query, query_tokens, fused, bm25_ranked, vector_ranked,
                              self.chunk_lookup, self.chunk_terms, self._cross_encoder_state, self.cross_encoder_model_name)
        else:
            bm25_ranked = []
            vector_ranked = []
            fused = []
            reranked = []
                          
        # FR-15: 可引用性阈值过滤
        evidence = [hit for hit in reranked[:max(1, rerank_topm)] if hit.get("rerank", 0.0) > 0.05]

        citations = [
            make_citation(self.repo, hit, persist=save_citations, message_id=assistant_message_id)
            for hit in evidence
        ] if save_citations else []
        answer = ""
        if generate_answer_flag:
            answer = generate_answer(
                query=user_query_for_answer or query,
                citation_like=citations if save_citations else evidence,
                llm=llm or {},
                history_messages=history_messages or [],
                summary_text=summary_text,
            )
        return {"answer_md": answer, "citations": citations,
                "debug": {"bm25": bm25_ranked, "vector": vector_ranked, "fusion": fused, "rerank": reranked}}

    async def retrieve_stream(self, query, bm25_topn=50, vector_topn=50, fusion_k=60,
                 rerank_topk=30, rerank_topm=8, save_citations=True,
                 llm=None, history_messages=None, summary_text="",
                 user_query_for_answer=None, assistant_message_id=None):
        chunks = self._indexed_chunks()
        query_tokens = tokenize(query)
        if not query_tokens:
            raise ValueError("查询内容为空或不可解析。")

        if chunks:
            bm25_ranked = rank_bm25(query_tokens, bm25_topn, self.bm25_enabled, self.bm25_index, self.bm25_chunk_ids)
            vector_ranked = rank_dense(query, vector_topn, self.vector_enabled, self.embedding_service,
                                       self.vector_chunk_ids, self.vector_matrix, self.chroma_collection)
            fused = rrf_fusion(bm25_ranked, vector_ranked, fusion_k)[:max(1, rerank_topk)]
            reranked = rerank(query, query_tokens, fused, bm25_ranked, vector_ranked,
                              self.chunk_lookup, self.chunk_terms, self._cross_encoder_state, self.cross_encoder_model_name)
        else:
            bm25_ranked = []
            vector_ranked = []
            fused = []
            reranked = []
        
        # FR-15: 可引用性阈值过滤 (过滤掉 rerank_score <= 0.2 或相关度极低的切片)
        evidence = [hit for hit in reranked[:max(1, rerank_topm)] if hit.get("rerank", 0.0) > 0.05]

        citations = [
            make_citation(self.repo, hit, persist=save_citations, message_id=assistant_message_id)
            for hit in evidence
        ] if save_citations else []
        
        # 产生第一条消息作为前置 metadata
        yield {"type": "metadata", "citations": citations, 
               "debug": {"bm25": bm25_ranked, "vector": vector_ranked, "fusion": fused, "rerank": reranked}}
        
        # 产生文本 chunk
        async for chunk in generate_answer_stream(
            query=user_query_for_answer or query,
            citation_like=citations if save_citations else evidence,
            llm=llm or {},
            history_messages=history_messages or [],
            summary_text=summary_text,
        ):
            yield {"type": "chunk", "content": chunk}


    def chat(self, session_id, query, topn, fusion, rerank, llm, request_id=None):
        turn = self.session_service.start_turn(session_id=session_id, query=query, request_id=request_id)
        try:
            result = self.retrieve(
                query=turn.retrieval_query,
                bm25_topn=topn.get("bm25", settings.TOPN_BM25),
                vector_topn=topn.get("vector", settings.TOPN_VECTOR),
                fusion_k=fusion.get("k", settings.FUSION_K),
                rerank_topk=rerank.get("topk", settings.RERANK_TOPK),
                rerank_topm=rerank.get("topm", settings.RERANK_TOPM),
                save_citations=True,
                llm=llm,
                history_messages=turn.prompt_context["recent_messages"],
                summary_text=turn.prompt_context["summary_text"],
                user_query_for_answer=query,
                generate_answer_flag=True,
                assistant_message_id=turn.assistant_message["msg_id"],
            )
            result["debug"]["retrieval_query"] = turn.retrieval_query
            completion = self.session_service.complete_turn(
                session_id=turn.session["session_id"],
                assistant_message_id=turn.assistant_message["msg_id"],
                answer_md=result["answer_md"],
                citations=result["citations"],
                debug=result["debug"],
            )
            return {
                "session_id": turn.session["session_id"],
                "user_message_id": turn.user_message["msg_id"],
                "assistant_message_id": turn.assistant_message["msg_id"],
                "answer_md": result["answer_md"],
                "citations": result["citations"],
                "debug": result["debug"],
                "session": completion["session"],
            }
        except Exception as exc:
            self.session_service.fail_turn(
                session_id=turn.session["session_id"],
                assistant_message_id=turn.assistant_message["msg_id"],
                error_message=str(exc),
            )
            raise

    async def chat_stream(self, session_id, query, topn, fusion, rerank, llm, request_id=None):
        turn = self.session_service.start_turn(session_id=session_id, query=query, request_id=request_id)
        full_answer: List[str] = []
        citations = []
        debug_info: Dict[str, Any] = {}

        try:
            async for item in self.retrieve_stream(
                query=turn.retrieval_query,
                bm25_topn=topn.get("bm25", settings.TOPN_BM25),
                vector_topn=topn.get("vector", settings.TOPN_VECTOR),
                fusion_k=fusion.get("k", settings.FUSION_K),
                rerank_topk=rerank.get("topk", settings.RERANK_TOPK),
                rerank_topm=rerank.get("topm", settings.RERANK_TOPM),
                save_citations=True,
                llm=llm,
                history_messages=turn.prompt_context["recent_messages"],
                summary_text=turn.prompt_context["summary_text"],
                user_query_for_answer=query,
                assistant_message_id=turn.assistant_message["msg_id"],
            ):
                if getattr(item, "get", None) and item.get("type") == "metadata":
                    citations = item.get("citations", [])
                    debug_info = item.get("debug", {})
                    debug_info["retrieval_query"] = turn.retrieval_query
                    yield {
                        "type": "metadata",
                        "session_id": turn.session["session_id"],
                        "user_message_id": turn.user_message["msg_id"],
                        "assistant_message_id": turn.assistant_message["msg_id"],
                        "citations": citations,
                        "debug": debug_info,
                        "session": turn.session,
                    }
                elif getattr(item, "get", None) and item.get("type") == "chunk":
                    chunk_str = item.get("content", "")
                    full_answer.append(chunk_str)
                    yield {"type": "chunk", "content": chunk_str}

            final_answer_md = "".join(full_answer)
            completion = self.session_service.complete_turn(
                session_id=turn.session["session_id"],
                assistant_message_id=turn.assistant_message["msg_id"],
                answer_md=final_answer_md,
                citations=citations,
                debug=debug_info,
            )
            yield {
                "type": "completed",
                "session_id": turn.session["session_id"],
                "assistant_message_id": turn.assistant_message["msg_id"],
                "session": completion["session"],
            }
        except Exception as exc:
            self.session_service.fail_turn(
                session_id=turn.session["session_id"],
                assistant_message_id=turn.assistant_message["msg_id"],
                error_message=str(exc),
                partial_content="".join(full_answer),
            )
            raise

    def get_session_history(self, session_id, limit=50):
        return {"session_id": session_id, "messages": self.session_service.list_messages(session_id=session_id, limit=limit)}

    def create_session(self, title=None):
        return self.session_service.create_session(title=title)

    def list_sessions(self, limit=20, status="active"):
        return {"items": self.session_service.list_sessions(limit=limit, status=status)}

    def get_session_detail(self, session_id, message_limit=50):
        return self.session_service.get_session_detail(session_id=session_id, message_limit=message_limit)

    def update_session(self, session_id, title=None, status=None):
        return self.session_service.update_session(session_id=session_id, title=title, status=status)

    def delete_session(self, session_id):
        return self.session_service.delete_session(session_id=session_id)

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

    def get_document_file(self, doc_id: str) -> Dict[str, Any]:
        doc = self.repo.get_document(doc_id, include_text=False)
        if doc is None:
            raise KeyError("文档不存在")
        file_path = self._ensure_original_viewable(doc)
        media_type = doc.get("mime_type") or mimetypes.guess_type(doc.get("original_file_name") or file_path.name)[0] or "application/octet-stream"
        return {
            "doc": doc,
            "file_path": file_path,
            "media_type": media_type,
            "file_name": doc.get("original_file_name") or file_path.name,
        }

    def get_citation_open_target(self, citation_id: str) -> Dict[str, Any]:
        citation = self.repo.get_citation(citation_id)
        if citation is None:
            raise KeyError("引用不存在")

        doc = self.repo.get_document(citation["doc_id"], include_text=False)
        chunk = self.chunk_lookup.get(citation["chunk_id"])
        if doc is None or chunk is None:
            raise KeyError("引用对应文档或片段不存在")

        self._ensure_original_viewable(doc)

        doc_id = doc["doc_id"]
        download_url = f"{settings.API_PREFIX}/docs/{doc_id}/file"
        if doc["doc_type"] == "pdf":
            page = chunk.page_start or citation["payload"].get("location", {}).get("page")
            page_part = int(page) if page else None
            url = download_url if page_part is None else f"{download_url}#page={page_part}"
            segment_label = f"第 {page_part} 页" if page_part else "原始 PDF"
            return {
                "doc_id": doc_id,
                "title": doc["title"],
                "doc_type": doc["doc_type"],
                "target_kind": "pdf",
                "url": url,
                "page": page_part,
                "segment_label": segment_label,
                "download_url": download_url,
                "viewer_ready": True,
            }

        locator = chunk.locator_json or {}
        paragraph_start = locator.get("paragraph_start")
        paragraph_end = locator.get("paragraph_end")
        if paragraph_start and paragraph_end:
            if paragraph_start == paragraph_end:
                segment_label = f"第 {paragraph_start} 段"
            else:
                segment_label = f"第 {paragraph_start}-{paragraph_end} 段"
        else:
            segment_label = citation["payload"].get("location", {}).get("section") or "定位片段"

        return {
            "doc_id": doc_id,
            "title": doc["title"],
            "doc_type": doc["doc_type"],
            "target_kind": "text_viewer",
            "url": f"/document-viewer/?doc_id={doc_id}&citation_id={citation_id}",
            "page": None,
            "segment_label": segment_label,
            "download_url": download_url,
            "viewer_ready": True,
        }

    def get_document_viewer_content(self, doc_id: str, citation_id: str) -> Dict[str, Any]:
        doc = self.repo.get_document(doc_id)
        if doc is None:
            raise KeyError("文档不存在")

        citation = self.repo.get_citation(citation_id)
        if citation is None or citation["doc_id"] != doc_id:
            raise KeyError("引用不存在")

        chunk = self.chunk_lookup.get(citation["chunk_id"])
        if chunk is None:
            raise KeyError("引用片段不存在")

        self._ensure_original_viewable(doc)

        full_text = doc.get("text", "")
        highlight = self._normalize_highlight_range(full_text, chunk.start_pos, chunk.end_pos)

        return {
            "doc_id": doc_id,
            "title": doc["title"],
            "doc_type": doc["doc_type"],
            "viewer_mode": doc.get("viewer_mode") or "structured_text",
            "download_url": f"{settings.API_PREFIX}/docs/{doc_id}/file",
            "text": full_text,
            "highlight": highlight,
            "citation_meta": {
                "section": chunk.section,
                "article_no": chunk.article_no,
                "snippet": citation["payload"].get("snippet", ""),
            },
        }

    # ─── 实验评测 ────────────────────────────────────────
    def run_experiment(self, dataset, topn, fusion, rerank, dataset_version: Optional[str] = None):
        if not dataset:
            raise ValueError("实验数据集不能为空。")

        rerank_options = rerank or {}
        metrics_totals = {
            "bm25_only": {"recall@5": 0.0, "mrr": 0.0, "hit@5": 0.0},
            "vector_only": {"recall@5": 0.0, "mrr": 0.0, "hit@5": 0.0},
            "hybrid_no_rerank": {"recall@5": 0.0, "mrr": 0.0, "hit@5": 0.0},
            "hybrid_rerank": {"recall@5": 0.0, "mrr": 0.0, "hit@5": 0.0},
        }
        case_results = []

        for case_index, case in enumerate(dataset, start=1):
            query = case["query"]
            relevant_chunk_ids = set(case.get("relevant_chunk_ids", []))
            relevant_doc_ids = set(case.get("relevant_doc_ids", []))
            if not relevant_chunk_ids and not relevant_doc_ids:
                raise ValueError("每个实验样本至少需要 relevant_chunk_ids 或 relevant_doc_ids。")

            group_rankings = self._build_experiment_group_rankings(
                query=query,
                topn=topn,
                fusion=fusion,
                rerank_options=rerank_options,
            )
            case_group_results: Dict[str, Any] = {}
            for group_name, ranking_entries in group_rankings.items():
                evaluation = self._evaluate_experiment_group(
                    ranking_entries,
                    relevant_chunk_ids=relevant_chunk_ids,
                    relevant_doc_ids=relevant_doc_ids,
                )
                case_group_results[group_name] = {
                    **evaluation,
                    "top5_chunk_ids": [item["chunk_id"] for item in ranking_entries],
                    "top5_doc_ids": [item["doc_id"] for item in ranking_entries],
                    "entries": ranking_entries,
                }
                metrics_totals[group_name]["recall@5"] += evaluation["recall@5"]
                metrics_totals[group_name]["mrr"] += evaluation["mrr"]
                metrics_totals[group_name]["hit@5"] += evaluation["hit@5"]

            case_results.append(
                {
                    "case_id": case.get("case_id") or f"case_{case_index:02d}",
                    "query": query,
                    "relevant_chunk_ids": sorted(relevant_chunk_ids),
                    "relevant_doc_ids": sorted(relevant_doc_ids),
                    "notes": case.get("notes"),
                    "groups": case_group_results,
                    "baseline_top5": case_group_results["vector_only"]["top5_chunk_ids"],
                    "improved_top5": case_group_results["hybrid_rerank"]["top5_chunk_ids"],
                    "baseline_recall@5": case_group_results["vector_only"]["recall@5"],
                    "baseline_mrr": case_group_results["vector_only"]["mrr"],
                    "improved_recall@5": case_group_results["hybrid_rerank"]["recall@5"],
                    "improved_mrr": case_group_results["hybrid_rerank"]["mrr"],
                }
            )

        total_cases = len(dataset)
        groups_metrics = {
            name: {
                "recall@5": round(values["recall@5"] / total_cases, 4),
                "mrr": round(values["mrr"] / total_cases, 4),
                "hit@5": round(values["hit@5"] / total_cases, 4),
            }
            for name, values in metrics_totals.items()
        }

        resolved_dataset_version = dataset_version or self._compute_dataset_version(dataset)
        created_at = now_iso()
        config = {
            "dataset_version": resolved_dataset_version,
            "corpus_version": self._get_corpus_version(),
            "chunk_strategy_version": CHUNK_STRATEGY_VERSION,
            "vector_backend": settings.VECTOR_DB_BACKEND,
            "embedding_provider": settings.EMBEDDING_PROVIDER,
            "embedding_model": self.embedding_service.name,
            "rerank_provider": settings.RERANK_PROVIDER,
            "rerank_model": settings.SILICONFLOW_RERANK_MODEL
            if (settings.RERANK_PROVIDER or "").strip().lower() == "siliconflow"
            else self.cross_encoder_model_name,
            "topn": topn,
            "fusion": fusion,
            "rerank": rerank_options,
        }
        metrics = {
            "groups": groups_metrics,
            "baseline": groups_metrics["vector_only"],
            "improved": groups_metrics["hybrid_rerank"],
            "total_cases": total_cases,
            "cases": case_results,
        }
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        mode = "four_group_retrieval_benchmark"
        self.repo.save_run(run_id, mode, config, metrics, created_at)
        return {
            "run_id": run_id,
            "mode": mode,
            "config": config,
            "metrics": metrics,
            "created_at": created_at,
        }

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

    def _build_experiment_group_rankings(self, query, topn, fusion, rerank_options):
        query_tokens = tokenize(query)
        if not query_tokens:
            raise ValueError("查询内容为空或不可解析。")

        bm25_ranked = rank_bm25(
            query_tokens,
            topn.get("bm25", settings.TOPN_BM25),
            self.bm25_enabled,
            self.bm25_index,
            self.bm25_chunk_ids,
        )
        vector_ranked = rank_dense(
            query,
            topn.get("vector", settings.TOPN_VECTOR),
            self.vector_enabled,
            self.embedding_service,
            self.vector_chunk_ids,
            self.vector_matrix,
            self.chroma_collection,
        )
        fused = rrf_fusion(bm25_ranked, vector_ranked, fusion.get("k", settings.FUSION_K))[
            : max(5, rerank_options.get("topk", settings.RERANK_TOPK))
        ]
        reranked = rerank(
            query,
            query_tokens,
            fused,
            bm25_ranked,
            vector_ranked,
            self.chunk_lookup,
            self.chunk_terms,
            self._cross_encoder_state,
            self.cross_encoder_model_name,
        )

        bm25_map = {item["chunk_id"]: float(item.get("score", 0.0)) for item in bm25_ranked}
        vector_map = {item["chunk_id"]: float(item.get("score", 0.0)) for item in vector_ranked}
        rrf_map = {item["chunk_id"]: float(item.get("rrf", 0.0)) for item in fused}
        rerank_map = {item["chunk_id"]: float(item.get("rerank", 0.0)) for item in reranked}

        return {
            "bm25_only": self._serialize_ranking_entries(bm25_ranked[:5], bm25_map, vector_map, rrf_map, rerank_map),
            "vector_only": self._serialize_ranking_entries(vector_ranked[:5], bm25_map, vector_map, rrf_map, rerank_map),
            "hybrid_no_rerank": self._serialize_ranking_entries(fused[:5], bm25_map, vector_map, rrf_map, rerank_map),
            "hybrid_rerank": self._serialize_ranking_entries(reranked[:5], bm25_map, vector_map, rrf_map, rerank_map),
        }

    def _serialize_ranking_entries(self, ranking_items, bm25_map, vector_map, rrf_map, rerank_map):
        entries = []
        for rank, item in enumerate(ranking_items, start=1):
            chunk_id = item.get("chunk_id")
            chunk = self.chunk_lookup.get(chunk_id)
            if chunk is None:
                continue
            entries.append(
                {
                    "rank": rank,
                    "chunk_id": chunk_id,
                    "doc_id": chunk.doc_id,
                    "section": chunk.section,
                    "article_no": chunk.article_no,
                    "snippet": chunk.chunk_text[:200],
                    "matched_relevant_chunk": False,
                    "matched_relevant_doc": False,
                    "scores": {
                        "bm25": round(float(bm25_map.get(chunk_id, 0.0)), 6),
                        "vector": round(float(vector_map.get(chunk_id, 0.0)), 6),
                        "rrf": round(float(rrf_map.get(chunk_id, 0.0)), 6),
                        "rerank": round(float(rerank_map.get(chunk_id, 0.0)), 6),
                    },
                }
            )
        return entries

    def _evaluate_experiment_group(self, ranking_entries, *, relevant_chunk_ids, relevant_doc_ids):
        uses_chunk_labels = bool(relevant_chunk_ids)
        relevant_count = max(1, len(relevant_chunk_ids) if uses_chunk_labels else len(relevant_doc_ids))
        matched_targets = set()
        first_hit_rank = None

        for entry in ranking_entries:
            matched_chunk = entry["chunk_id"] in relevant_chunk_ids
            matched_doc = entry["doc_id"] in relevant_doc_ids
            entry["matched_relevant_chunk"] = matched_chunk
            entry["matched_relevant_doc"] = matched_doc
            hit = matched_chunk if uses_chunk_labels else matched_doc
            if hit:
                target = entry["chunk_id"] if uses_chunk_labels else entry["doc_id"]
                matched_targets.add(target)
                if first_hit_rank is None:
                    first_hit_rank = entry["rank"]

        recall = len(matched_targets) / relevant_count
        hit_at_5 = 1.0 if first_hit_rank is not None else 0.0
        mrr = 0.0 if first_hit_rank is None else 1.0 / first_hit_rank
        return {
            "recall@5": round(recall, 4),
            "hit@5": round(hit_at_5, 4),
            "mrr": round(mrr, 4),
            "first_hit_rank": first_hit_rank,
        }

    def _compute_dataset_version(self, dataset) -> str:
        normalized_cases = []
        for index, case in enumerate(dataset, start=1):
            normalized_cases.append(
                {
                    "case_id": case.get("case_id") or f"case_{index:02d}",
                    "query": case["query"],
                    "relevant_chunk_ids": sorted(case.get("relevant_chunk_ids", [])),
                    "relevant_doc_ids": sorted(case.get("relevant_doc_ids", [])),
                    "notes": case.get("notes") or "",
                }
            )
        raw = json.dumps(normalized_cases, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _get_corpus_version(self) -> str:
        docs = self.repo.list_documents(include_text=False)
        parts = []
        for doc in docs:
            if doc.get("parse_status") != "indexed":
                continue
            source_fingerprint = doc.get("source_fingerprint") or f"legacy:{doc['doc_id']}"
            strategy_version = doc.get("chunk_strategy_version") or CHUNK_STRATEGY_VERSION
            parts.append(f"{source_fingerprint}:{strategy_version}")
        raw = "|".join(sorted(parts)) or "empty_corpus"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _indexed_chunks(self):
        with self._lock:
            return list(self.chunk_lookup.values())


# ─── 懒加载引擎实例（router 仍通过 from app.core.rag_engine import engine 使用）
@lru_cache(maxsize=1)
def get_engine() -> LegalRagService:
    return LegalRagService(default_chunk_size=settings.CHUNK_SIZE, default_chunk_overlap=settings.CHUNK_OVERLAP)


class _LazyEngineProxy:
    def __getattr__(self, name: str):
        return getattr(get_engine(), name)


engine = _LazyEngineProxy()
