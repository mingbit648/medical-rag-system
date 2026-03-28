from fastapi import APIRouter, Depends, HTTPException

from app.core.rag_engine import get_engine
from app.dependencies import require_admin, require_kb_read_access
from app.models.schemas import RetrieveDebugRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


@router.post("/debug")
async def retrieve_debug(payload: RetrieveDebugRequest, user=Depends(require_admin)):
    trace_id = make_trace_id()
    require_kb_read_access(user, payload.kb_id)
    try:
        result = get_engine().retrieve(
            query=payload.query,
            kb_id=payload.kb_id,
            bm25_topn=payload.topn.bm25,
            vector_topn=payload.topn.vector,
            fusion_k=payload.fusion.k,
            rerank_topk=payload.rerank.topk,
            rerank_topm=payload.rerank.topm,
            save_citations=False,
            generate_answer_flag=False,
        )
        return ok(
            {
                "query": payload.query,
                "kb_id": payload.kb_id,
                "bm25": result["debug"]["bm25"],
                "vector": result["debug"]["vector"],
                "fusion": result["debug"]["fusion"],
                "rerank": result["debug"]["rerank"],
            },
            trace_id=trace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
