from fastapi import APIRouter, Depends, HTTPException

from app.core.rag_engine import get_engine
from app.dependencies import require_current_user
from app.models.schemas import KnowledgeBaseCreateRequest, KnowledgeBaseUpdateRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


def _raise_kb_error(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("")
async def list_knowledge_bases(user=Depends(require_current_user)):
    trace_id = make_trace_id()
    items = get_engine().list_knowledge_bases(user_id=user["user_id"], user_role=user["role"])
    return ok({"items": items}, trace_id=trace_id)


@router.post("")
async def create_knowledge_base(payload: KnowledgeBaseCreateRequest, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    try:
        result = get_engine().create_knowledge_base(
            user_id=user["user_id"],
            name=payload.name,
            description=payload.description,
        )
        return ok(result, trace_id=trace_id)
    except Exception as exc:
        _raise_kb_error(exc)


@router.patch("/{kb_id}")
async def update_knowledge_base(kb_id: str, payload: KnowledgeBaseUpdateRequest, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    try:
        result = get_engine().update_knowledge_base(
            user_id=user["user_id"],
            user_role=user["role"],
            kb_id=kb_id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
        )
        return ok(result, trace_id=trace_id)
    except Exception as exc:
        _raise_kb_error(exc)


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: str, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    try:
        result = get_engine().delete_knowledge_base(user_id=user["user_id"], kb_id=kb_id)
        return ok(result, trace_id=trace_id)
    except Exception as exc:
        _raise_kb_error(exc)
