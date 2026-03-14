import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app.core.rag_engine import engine
from app.models.schemas import (
    ChatCompletionRequest,
    ChatSessionCreateRequest,
    ChatSessionMessageRequest,
    ChatSessionUpdateRequest,
)
from app.services import DuplicateRequestError, SessionBusyError, SessionNotFoundError, SessionStateError
from app.utils.response import make_trace_id, ok


router = APIRouter()


def _raise_chat_http_error(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, (KeyError, SessionNotFoundError)):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (SessionBusyError, SessionStateError, DuplicateRequestError)):
        raise HTTPException(status_code=409, detail=str(exc))
    raise exc


def _normalize_status_filter(status: str | None) -> str | None:
    if status is None:
        return "active"
    lowered = status.strip().lower()
    if lowered == "all":
        return None
    return lowered or "active"


async def _stream_chat_response(request_payload: ChatCompletionRequest | ChatSessionMessageRequest, *, session_id: str | None):
    trace_id = make_trace_id()

    async def event_stream():
        current_session_id = session_id
        user_message_id = None
        assistant_message_id = None
        session_payload = None
        answer_chunks: list[str] = []
        turn_completed = False
        try:
            citations = []

            async for item in engine.chat_stream(
                session_id=session_id,
                query=request_payload.query,
                request_id=request_payload.request_id,
                topn=request_payload.topn.model_dump(),
                fusion=request_payload.fusion.model_dump(),
                rerank=request_payload.rerank.model_dump(),
                llm=request_payload.llm.model_dump(),
            ):
                item_type = item.get("type")
                if item_type == "metadata":
                    citations = item.get("citations", [])
                    current_session_id = item.get("session_id", session_id)
                    user_message_id = item.get("user_message_id")
                    assistant_message_id = item.get("assistant_message_id")
                    session_payload = item.get("session")
                    yield f"event: metadata\ndata: {json.dumps(jsonable_encoder(item), ensure_ascii=False)}\n\n"
                elif item_type == "chunk":
                    chunk_text = item.get("content", "")
                    if chunk_text:
                        answer_chunks.append(chunk_text)
                        yield f"event: token\ndata: {json.dumps(chunk_text, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0)
                elif item_type == "completed":
                    turn_completed = True
                    session_payload = item.get("session", session_payload)
                    assistant_message_id = item.get("assistant_message_id", assistant_message_id)

            done_payload = {
                "session_id": current_session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "citations": citations,
                "session": session_payload,
                "trace_id": trace_id,
            }
            yield f"event: done\ndata: {json.dumps(jsonable_encoder(done_payload), ensure_ascii=False)}\n\n"
        except Exception as exc:
            if current_session_id and assistant_message_id and not turn_completed:
                try:
                    engine.session_service.fail_turn(
                        session_id=current_session_id,
                        assistant_message_id=assistant_message_id,
                        error_message=str(exc),
                        partial_content="".join(answer_chunks),
                    )
                except Exception:
                    pass
            err = {"message": str(exc), "trace_id": trace_id}
            yield f"event: error\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/sessions")
async def create_session(request: ChatSessionCreateRequest):
    trace_id = make_trace_id()
    try:
        return ok(engine.create_session(title=request.title), trace_id=trace_id)
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.get("/sessions")
async def list_sessions(limit: int = 20, status: str | None = "active"):
    trace_id = make_trace_id()
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=400, detail="limit 必须在 1~200 之间")
    try:
        return ok(engine.list_sessions(limit=limit, status=_normalize_status_filter(status)), trace_id=trace_id)
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str, message_limit: int = 50):
    trace_id = make_trace_id()
    if message_limit <= 0 or message_limit > 500:
        raise HTTPException(status_code=400, detail="message_limit 必须在 1~500 之间")
    try:
        return ok(engine.get_session_detail(session_id=session_id, message_limit=message_limit), trace_id=trace_id)
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.get("/sessions/{session_id}/messages")
async def list_session_messages(session_id: str, limit: int = 50, before_seq: int | None = None):
    trace_id = make_trace_id()
    if limit <= 0 or limit > 500:
        raise HTTPException(status_code=400, detail="limit 必须在 1~500 之间")
    try:
        return ok(
            {
                "session_id": session_id,
                "messages": engine.get_session_history(session_id=session_id, limit=limit)["messages"]
                if before_seq is None
                else engine.session_service.list_messages(session_id=session_id, limit=limit, before_seq=before_seq),
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, request: ChatSessionUpdateRequest):
    trace_id = make_trace_id()
    try:
        return ok(
            engine.update_session(session_id=session_id, title=request.title, status=request.status),
            trace_id=trace_id,
        )
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    trace_id = make_trace_id()
    try:
        engine.delete_session(session_id=session_id)
        return ok({"session_id": session_id, "deleted": True}, trace_id=trace_id)
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.post("/sessions/{session_id}/messages")
async def create_session_message(session_id: str, request: ChatSessionMessageRequest):
    trace_id = make_trace_id()
    try:
        result = engine.chat(
            session_id=session_id,
            query=request.query,
            request_id=request.request_id,
            topn=request.topn.model_dump(),
            fusion=request.fusion.model_dump(),
            rerank=request.rerank.model_dump(),
            llm=request.llm.model_dump(),
        )
        return ok(result, trace_id=trace_id)
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.post("/sessions/{session_id}/messages:stream")
async def create_session_message_stream(session_id: str, request: ChatSessionMessageRequest):
    return await _stream_chat_response(request, session_id=session_id)


@router.post("/completions")
async def chat_completions(request: ChatCompletionRequest):
    trace_id = make_trace_id()
    try:
        result = engine.chat(
            session_id=request.session_id,
            query=request.query,
            request_id=request.request_id,
            topn=request.topn.model_dump(),
            fusion=request.fusion.model_dump(),
            rerank=request.rerank.model_dump(),
            llm=request.llm.model_dump(),
        )
        return ok(result, trace_id=trace_id)
    except Exception as exc:
        _raise_chat_http_error(exc)


@router.post("/completions:stream")
async def chat_completions_stream(request: ChatCompletionRequest):
    return await _stream_chat_response(request, session_id=request.session_id)


@router.get("/history/{session_id}")
async def chat_history(session_id: str, limit: int = 50):
    trace_id = make_trace_id()
    if limit <= 0 or limit > 500:
        raise HTTPException(status_code=400, detail="limit 必须在 1~500 之间")
    try:
        return ok(engine.get_session_history(session_id=session_id, limit=limit), trace_id=trace_id)
    except Exception as exc:
        _raise_chat_http_error(exc)
