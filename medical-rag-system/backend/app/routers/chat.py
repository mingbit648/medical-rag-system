import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.rag_engine import engine
from app.models.schemas import ChatCompletionRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


@router.post("/completions")
async def chat_completions(request: ChatCompletionRequest):
    trace_id = make_trace_id()
    try:
        result = engine.chat(
            session_id=request.session_id,
            query=request.query,
            topn=request.topn.model_dump(),
            fusion=request.fusion.model_dump(),
            rerank=request.rerank.model_dump(),
            llm=request.llm.model_dump(),
        )
        return ok(
            {
                "session_id": result["session_id"],
                "answer_md": result["answer_md"],
                "citations": result["citations"],
            },
            trace_id=trace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/completions:stream")
async def chat_completions_stream(request: ChatCompletionRequest):
    trace_id = make_trace_id()

    async def event_stream():
        try:
            citations = []
            session_id = request.session_id
            
            async for item in engine.chat_stream(
                session_id=request.session_id,
                query=request.query,
                topn=request.topn.model_dump(),
                fusion=request.fusion.model_dump(),
                rerank=request.rerank.model_dump(),
                llm=request.llm.model_dump(),
            ):
                if item.get("type") == "metadata":
                    citations = item.get("citations", [])
                    session_id = item.get("session_id", request.session_id)
                elif item.get("type") == "chunk":
                    chunk_text = item.get("content", "")
                    if chunk_text:
                        # 对于真正的 SSE token，尽量不要再套一层字符串避免解析问题，
                        # 把换行符等做正确转义
                        import json
                        yield f"event: token\ndata: {json.dumps(chunk_text, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0)

            done_payload = {
                "session_id": session_id,
                "citations": citations,
                "trace_id": trace_id,

            }
            yield f"event: done\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            err = {"message": str(exc), "trace_id": trace_id}
            yield f"event: error\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history/{session_id}")
async def chat_history(session_id: str, limit: int = 50):
    trace_id = make_trace_id()
    if limit <= 0 or limit > 500:
        raise HTTPException(status_code=400, detail="limit 必须在 1~500 之间")
    return ok(engine.get_session_history(session_id=session_id, limit=limit), trace_id=trace_id)
