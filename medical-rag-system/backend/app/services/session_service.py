import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.session_context import build_retrieval_query, build_session_summary
from app.core.text_utils import PRONOUN_REF_PATTERN, now_iso
from app.repositories import PgRepository


DEFAULT_SESSION_TITLE = "新对话"
STALE_STREAM_MESSAGE = "上一次回复已中断，请重新提问。"


class SessionNotFoundError(KeyError):
    pass


class SessionBusyError(RuntimeError):
    pass


class SessionStateError(RuntimeError):
    pass


class DuplicateRequestError(RuntimeError):
    pass


@dataclass
class TurnStartContext:
    session: Dict[str, Any]
    request_id: str
    user_message: Dict[str, Any]
    assistant_message: Dict[str, Any]
    prompt_context: Dict[str, Any]
    retrieval_query: str


class SessionService:
    def __init__(self, repo: PgRepository):
        self.repo = repo

    def create_session(self, title: Optional[str] = None) -> Dict[str, Any]:
        session_id = f"s_{uuid.uuid4().hex[:12]}"
        now = now_iso()
        return self.repo.create_session(
            session_id=session_id,
            title=(title or DEFAULT_SESSION_TITLE).strip() or DEFAULT_SESSION_TITLE,
            created_at=now,
            updated_at=now,
            last_active_at=now,
            message_count=0,
            status="active",
            meta_json={"preview": "", "last_message_role": None},
        )

    def list_sessions(self, limit: int = 20, status: Optional[str] = "active") -> List[Dict[str, Any]]:
        return self.repo.list_sessions(limit=limit, status=status)

    def get_session(self, session_id: str) -> Dict[str, Any]:
        session = self.repo.get_session(session_id)
        if session is None:
            raise SessionNotFoundError("会话不存在")
        return session

    def get_session_detail(self, session_id: str, message_limit: int = 50) -> Dict[str, Any]:
        with self.repo.transaction() as cur:
            session = self.repo._get_session(cur, session_id, for_update=True)
            if session is None:
                raise SessionNotFoundError("会话不存在")
            self._repair_stale_streams(cur, session)
            session = self.repo._get_session(cur, session_id, for_update=False)
            messages = self.repo._list_messages(
                cur,
                session_id=session_id,
                limit=message_limit,
                statuses=None,
                include_citations=True,
            )
            snapshot = self.repo._get_active_context_snapshot(cur, session_id)
            return {"session": session, "messages": messages, "active_summary": snapshot}

    def list_messages(self, session_id: str, limit: int = 50, before_seq: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.repo.transaction() as cur:
            session = self.repo._get_session(cur, session_id, for_update=True)
            if session is None:
                raise SessionNotFoundError("会话不存在")
            self._repair_stale_streams(cur, session)
            return self.repo._list_messages(
                cur,
                session_id=session_id,
                limit=limit,
                before_seq=before_seq,
                statuses=None,
                include_citations=True,
            )

    def update_session(self, session_id: str, *, title: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
        normalized_status = status.strip().lower() if status else None
        if normalized_status and normalized_status not in {"active", "archived", "deleted"}:
            raise ValueError("status 仅支持 active / archived / deleted")

        session = self.get_session(session_id)
        next_title = title.strip() if title else None
        if next_title == "":
            raise ValueError("title 不能为空")

        updated = self.repo.update_session(
            session_id=session_id,
            title=next_title if next_title else None,
            status=normalized_status,
            updated_at=now_iso(),
            last_active_at=session.get("last_active_at"),
            meta_json=session.get("meta_json") or {},
        )
        if updated is None:
            raise SessionNotFoundError("会话不存在")
        return updated

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        session = self.get_session(session_id)
        deleted = self.repo.update_session(
            session_id=session_id,
            status="deleted",
            updated_at=now_iso(),
            last_active_at=session.get("last_active_at"),
            meta_json=session.get("meta_json") or {},
        )
        if deleted is None:
            raise SessionNotFoundError("会话不存在")
        return deleted

    def start_turn(self, *, session_id: Optional[str], query: str, request_id: Optional[str] = None) -> TurnStartContext:
        now = now_iso()
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query 不能为空")

        effective_request_id = (request_id or f"req_{uuid.uuid4().hex[:16]}").strip()
        if not effective_request_id:
            effective_request_id = f"req_{uuid.uuid4().hex[:16]}"

        with self.repo.transaction() as cur:
            session = self.repo._get_session(cur, session_id, for_update=True) if session_id else None
            if session_id and session is None:
                raise SessionNotFoundError("会话不存在")
            if session is None:
                session_id = f"s_{uuid.uuid4().hex[:12]}"
                self.repo._insert_session(
                    cur,
                    session_id=session_id,
                    title=self._derive_title(normalized_query),
                    created_at=now,
                    updated_at=now,
                    last_active_at=now,
                    message_count=0,
                    status="active",
                    meta_json={"preview": "", "last_message_role": None},
                )
                session = self.repo._get_session(cur, session_id, for_update=True)

            if session is None:
                raise SessionNotFoundError("会话不存在")
            if session.get("status") != "active":
                raise SessionStateError("当前会话不可写入，请恢复为 active 后再继续")

            self._repair_stale_streams(cur, session)

            if self.repo._request_id_exists(cur, session["session_id"], effective_request_id):
                raise DuplicateRequestError("重复请求，请刷新当前会话后重试")

            streaming_message = self.repo._find_streaming_message(cur, session["session_id"])
            if streaming_message is not None:
                raise SessionBusyError("当前会话仍有未完成回复，请稍后再试")

            prompt_context = self._build_prompt_context(cur, session["session_id"])
            retrieval_query = build_retrieval_query(
                normalized_query,
                summary_text=prompt_context["summary_text"],
                recent_messages=prompt_context["recent_messages"],
                short_query_chars=settings.RETRIEVAL_SHORT_QUERY_CHARS,
                max_recent_user_messages=settings.RETRIEVAL_HISTORY_USER_MESSAGES,
                pronoun_pattern=PRONOUN_REF_PATTERN,
            )

            next_seq = self.repo._get_next_session_seq(cur, session["session_id"])
            user_message_id = f"msg_{uuid.uuid4().hex[:16]}"
            assistant_message_id = f"msg_{uuid.uuid4().hex[:16]}"

            user_message = self.repo._insert_message(
                cur,
                msg_id=user_message_id,
                session_id=session["session_id"],
                session_seq=next_seq,
                role="user",
                content=normalized_query,
                created_at=now,
                updated_at=now,
                completed_at=now,
                status="completed",
                request_id=effective_request_id,
                message_type="question",
                meta_json={},
            )
            assistant_message = self.repo._insert_message(
                cur,
                msg_id=assistant_message_id,
                session_id=session["session_id"],
                session_seq=next_seq + 1,
                role="assistant",
                content="",
                created_at=now,
                updated_at=now,
                completed_at=None,
                status="streaming",
                request_id=effective_request_id,
                message_type="answer",
                meta_json={},
            )

            session_meta = session.get("meta_json") or {}
            session_meta.update(
                {
                    "preview": self._preview(normalized_query, 80),
                    "last_message_role": "user",
                    "last_user_query": self._preview(normalized_query, 160),
                }
            )
            title = session.get("title") or DEFAULT_SESSION_TITLE
            if session.get("message_count", 0) == 0 or title == DEFAULT_SESSION_TITLE:
                title = self._derive_title(normalized_query)
            updated_session = self.repo._update_session(
                cur,
                session["session_id"],
                title=title,
                updated_at=now,
                last_active_at=now,
                message_count=(session.get("message_count") or 0) + 2,
                meta_json=session_meta,
            )
            if updated_session is None:
                raise SessionNotFoundError("会话不存在")

            return TurnStartContext(
                session=updated_session,
                request_id=effective_request_id,
                user_message=user_message,
                assistant_message=assistant_message,
                prompt_context=prompt_context,
                retrieval_query=retrieval_query,
            )

    def complete_turn(
        self,
        *,
        session_id: str,
        assistant_message_id: str,
        answer_md: str,
        citations: List[Dict[str, Any]],
        debug: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = now_iso()
        with self.repo.transaction() as cur:
            session = self.repo._get_session(cur, session_id, for_update=True)
            if session is None:
                raise SessionNotFoundError("会话不存在")
            assistant_message = self.repo._get_message(cur, assistant_message_id, for_update=True)
            if assistant_message is None:
                raise SessionNotFoundError("消息不存在")

            message_meta = assistant_message.get("meta_json") or {}
            message_meta["citations_count"] = len(citations)
            if debug:
                message_meta["debug"] = debug

            updated_message = self.repo._update_message(
                cur,
                assistant_message_id,
                content=answer_md,
                status="completed",
                updated_at=now,
                completed_at=now,
                meta_json=message_meta,
            )
            session_meta = session.get("meta_json") or {}
            session_meta.update(
                {
                    "preview": self._preview(answer_md, 80),
                    "last_message_role": "assistant",
                }
            )
            updated_session = self.repo._update_session(
                cur,
                session_id,
                updated_at=now,
                last_active_at=now,
                meta_json=session_meta,
            )
            snapshot = self._refresh_summary(cur, session_id)
            updated_session = self.repo._get_session(cur, session_id)
            if updated_session is None or updated_message is None:
                raise SessionNotFoundError("会话不存在")
            if snapshot is not None:
                updated_session["active_summary_id"] = snapshot["snapshot_id"]
            updated_message["citations"] = citations
            return {"session": updated_session, "message": updated_message, "active_summary": snapshot}

    def fail_turn(
        self,
        *,
        session_id: str,
        assistant_message_id: str,
        error_message: str,
        partial_content: str = "",
    ) -> Dict[str, Any]:
        now = now_iso()
        with self.repo.transaction() as cur:
            session = self.repo._get_session(cur, session_id, for_update=True)
            if session is None:
                raise SessionNotFoundError("会话不存在")
            assistant_message = self.repo._get_message(cur, assistant_message_id, for_update=True)
            if assistant_message is None:
                raise SessionNotFoundError("消息不存在")

            failure_text = partial_content.strip() or f"生成失败：{error_message}"
            failure_text = failure_text.strip()
            message_meta = assistant_message.get("meta_json") or {}
            message_meta["error"] = error_message

            self.repo._delete_citations_for_message(cur, assistant_message_id)
            updated_message = self.repo._update_message(
                cur,
                assistant_message_id,
                content=failure_text,
                status="error",
                updated_at=now,
                completed_at=now,
                meta_json=message_meta,
            )
            session_meta = session.get("meta_json") or {}
            session_meta.update(
                {
                    "preview": self._preview(failure_text, 80),
                    "last_message_role": "assistant",
                }
            )
            updated_session = self.repo._update_session(
                cur,
                session_id,
                updated_at=now,
                last_active_at=now,
                meta_json=session_meta,
            )
            return {
                "session": updated_session,
                "message": updated_message,
            }

    def _build_prompt_context(self, cur, session_id: str) -> Dict[str, Any]:
        snapshot = self.repo._get_active_context_snapshot(cur, session_id)
        after_seq = snapshot["to_seq"] if snapshot else None
        recent_messages = self.repo._list_messages(
            cur,
            session_id=session_id,
            limit=settings.SESSION_CONTEXT_KEEP_RECENT_MESSAGES,
            after_seq=after_seq,
            statuses=["completed"],
            include_citations=False,
        )
        return {
            "summary_text": snapshot["summary_text"] if snapshot else "",
            "summary_to_seq": snapshot["to_seq"] if snapshot else 0,
            "recent_messages": recent_messages,
        }

    def _refresh_summary(self, cur, session_id: str) -> Optional[Dict[str, Any]]:
        completed_messages = self.repo._list_messages(
            cur,
            session_id=session_id,
            limit=settings.SESSION_SUMMARY_SOURCE_MESSAGES,
            statuses=["completed"],
            include_citations=False,
        )
        if len(completed_messages) <= settings.SESSION_SUMMARY_TRIGGER_MESSAGES:
            self.repo._clear_active_context_snapshot(cur, session_id)
            return None

        cutoff_messages = completed_messages[:-settings.SESSION_CONTEXT_KEEP_RECENT_MESSAGES]
        if not cutoff_messages:
            self.repo._clear_active_context_snapshot(cur, session_id)
            return None

        summary_text = build_session_summary(
            cutoff_messages,
            max_chars=settings.SESSION_SUMMARY_MAX_CHARS,
            max_user_items=settings.SESSION_SUMMARY_MAX_USER_ITEMS,
            max_assistant_items=settings.SESSION_SUMMARY_MAX_ASSISTANT_ITEMS,
            item_chars=settings.SESSION_SUMMARY_ITEM_MAX_CHARS,
        )
        if not summary_text:
            self.repo._clear_active_context_snapshot(cur, session_id)
            return None

        snapshot = self.repo._insert_context_snapshot(
            cur,
            snapshot_id=f"scs_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            from_seq=cutoff_messages[0]["session_seq"],
            to_seq=cutoff_messages[-1]["session_seq"],
            summary_text=summary_text,
            created_at=now_iso(),
            meta_json={"source_message_count": len(cutoff_messages)},
        )
        self.repo._set_active_context_snapshot(cur, session_id, snapshot["snapshot_id"])
        return snapshot

    def _repair_stale_streams(self, cur, session: Dict[str, Any]) -> None:
        streaming_message = self.repo._find_streaming_message(cur, session["session_id"])
        if streaming_message is None:
            return
        if not self._is_stale(streaming_message.get("updated_at") or streaming_message.get("created_at")):
            return
        self.repo._delete_citations_for_message(cur, streaming_message["msg_id"])
        meta_json = streaming_message.get("meta_json") or {}
        meta_json["error"] = "stream_interrupted"
        self.repo._update_message(
            cur,
            streaming_message["msg_id"],
            content=STALE_STREAM_MESSAGE,
            status="error",
            updated_at=now_iso(),
            completed_at=now_iso(),
            meta_json=meta_json,
        )
        session_meta = session.get("meta_json") or {}
        session_meta.update({"preview": STALE_STREAM_MESSAGE, "last_message_role": "assistant"})
        self.repo._update_session(
            cur,
            session["session_id"],
            updated_at=now_iso(),
            last_active_at=session.get("last_active_at"),
            meta_json=session_meta,
        )

    def _is_stale(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return True
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - value >= timedelta(seconds=settings.SESSION_STREAM_STALE_SECONDS)

    @staticmethod
    def _derive_title(query: str) -> str:
        title = " ".join((query or "").split()).strip()
        if not title:
            return DEFAULT_SESSION_TITLE
        return title[:28]

    @staticmethod
    def _preview(text: str, max_chars: int) -> str:
        normalized = " ".join((text or "").split()).strip()
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[: max_chars - 3].rstrip()}..."
