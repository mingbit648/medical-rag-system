from fastapi import APIRouter, HTTPException

from app.core.rag_engine import engine
from app.models.schemas import RetrieveDebugRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


@router.post("/debug")
async def retrieve_debug(request: RetrieveDebugRequest):
    trace_id = make_trace_id()
    try:
        result = engine.retrieve(
            query=request.query,
            bm25_topn=request.topn.bm25,
            vector_topn=request.topn.vector,
            fusion_k=request.fusion.k,
            rerank_topk=request.rerank.topk,
            rerank_topm=request.rerank.topm,
            save_citations=False,
            generate_answer_flag=False,
        )
        return ok(
            {
                "query": request.query,
                "bm25": result["debug"]["bm25"],
                "vector": result["debug"]["vector"],
                "fusion": result["debug"]["fusion"],
                "rerank": result["debug"]["rerank"],
            },
            trace_id=trace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
