from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.rag_engine import get_engine
from app.dependencies import require_current_user
from app.utils.response import make_trace_id, ok


router = APIRouter()


def _raise_conflict(message: str, *, code: str) -> None:
    raise HTTPException(status_code=409, detail={"code": code, "message": message})


@router.get("/{citation_id}/view")
async def citation_view(
    citation_id: str,
    context_before: int = Query(default=400, ge=0, le=5000),
    context_after: int = Query(default=400, ge=0, le=5000),
    user=Depends(require_current_user),
):
    trace_id = make_trace_id()
    try:
        result = get_engine().get_citation_view(
            user["user_id"],
            citation_id,
            context_before=context_before,
            context_after=context_after,
        )
        return ok(result, trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{citation_id}/open-target")
async def citation_open_target(citation_id: str, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    try:
        result = get_engine().get_citation_open_target(user["user_id"], citation_id)
        return ok(result, trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        _raise_conflict(str(exc), code="ORIGINAL_VIEW_UNAVAILABLE")
