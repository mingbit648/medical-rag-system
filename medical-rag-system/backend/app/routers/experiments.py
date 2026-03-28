from fastapi import APIRouter, Depends, HTTPException

from app.core.rag_engine import get_engine
from app.dependencies import require_admin, require_kb_read_access
from app.models.schemas import ExperimentRunRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


@router.post("/run")
async def run_experiment(payload: ExperimentRunRequest, user=Depends(require_admin)):
    trace_id = make_trace_id()
    require_kb_read_access(user, payload.kb_id)
    try:
        result = get_engine().run_experiment(
            kb_id=payload.kb_id,
            dataset=[item.model_dump() for item in payload.dataset],
            dataset_version=payload.dataset_version,
            topn=payload.topn.model_dump(),
            fusion=payload.fusion.model_dump(),
            rerank=payload.rerank.model_dump(),
        )
        return ok(result, trace_id=trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs/{run_id}")
async def get_run(run_id: str, kb_id: str, user=Depends(require_admin)):
    trace_id = make_trace_id()
    require_kb_read_access(user, kb_id)
    try:
        return ok(get_engine().get_run(kb_id, run_id), trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/runs")
async def list_runs(kb_id: str, limit: int = 20, user=Depends(require_admin)):
    trace_id = make_trace_id()
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=400, detail="limit 必须在 1~200 之间")
    require_kb_read_access(user, kb_id)
    return ok(get_engine().list_runs(kb_id, limit=limit), trace_id=trace_id)
