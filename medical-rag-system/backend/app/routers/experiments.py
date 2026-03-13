from fastapi import APIRouter, HTTPException

from app.core.rag_engine import engine
from app.models.schemas import ExperimentRunRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


@router.post("/run")
async def run_experiment(request: ExperimentRunRequest):
    trace_id = make_trace_id()
    try:
        result = engine.run_experiment(
            dataset=[item.model_dump() for item in request.dataset],
            topn=request.topn.model_dump(),
            fusion=request.fusion.model_dump(),
            rerank=request.rerank.model_dump(),
        )
        return ok(result, trace_id=trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    trace_id = make_trace_id()
    try:
        return ok(engine.get_run(run_id), trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/runs")
async def list_runs(limit: int = 20):
    trace_id = make_trace_id()
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=400, detail="limit 必须在 1~200 之间")
    return ok(engine.list_runs(limit=limit), trace_id=trace_id)
