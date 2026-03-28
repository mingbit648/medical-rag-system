from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.doc_ingestion import DuplicateDocumentError
from app.core.rag_engine import get_engine
from app.dependencies import require_current_user, require_kb_read_access, require_kb_write_access
from app.models.schemas import IndexRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


def _raise_conflict(message: str, *, code: str) -> None:
    raise HTTPException(status_code=409, detail={"code": code, "message": message})


def _resolve_document_for_user(doc_id: str, user):
    doc = get_engine().repo.get_document(doc_id, include_text=False)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_read_access(user, doc["kb_id"])
    return doc


def _resolve_document_for_write(doc_id: str, user):
    doc = get_engine().repo.get_document(doc_id, include_text=False)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_write_access(user, doc["kb_id"])
    return doc


@router.post("/import")
async def import_doc(
    file: UploadFile = File(...),
    kb_id: str = Form(...),
    source_url: Optional[str] = Form(default=None),
    doc_type: Optional[str] = Form(default=None),
    overwrite_doc_id: Optional[str] = Form(default=None),
    user=Depends(require_current_user),
):
    trace_id = make_trace_id()
    require_kb_write_access(user, kb_id)
    try:
        content = await file.read()
        if not content:
            raise ValueError("上传文件不能为空")
        result = get_engine().import_document(
            kb_id=kb_id,
            uploaded_by=user["user_id"],
            file_name=file.filename or "uploaded_file",
            content=content,
            doc_type=doc_type,
            source_url=source_url,
            overwrite_doc_id=overwrite_doc_id,
        )
        return ok(result, trace_id=trace_id)
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_ALREADY_EXISTS",
                "message": str(exc),
                "existing_doc": exc.existing_doc,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{doc_id}/index")
async def index_doc(doc_id: str, payload: IndexRequest, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    _resolve_document_for_write(doc_id, user)
    try:
        result = get_engine().enqueue_index_job(
            doc_id=doc_id,
            requested_by=user["user_id"],
            options=payload.model_dump(),
        )
        return ok(result, trace_id=trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{doc_id}/status")
async def get_doc_status(doc_id: str, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    _resolve_document_for_user(doc_id, user)
    try:
        return ok(get_engine().get_doc_status(doc_id), trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{doc_id}/file")
async def get_doc_file(doc_id: str, user=Depends(require_current_user)):
    _resolve_document_for_user(doc_id, user)
    try:
        result = get_engine().get_document_file(doc_id)
        return FileResponse(
            path=result["file_path"],
            media_type=result["media_type"],
            filename=result["file_name"],
            headers={"Content-Disposition": f'inline; filename="{result["file_name"]}"'},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        _raise_conflict(str(exc), code="ORIGINAL_VIEW_UNAVAILABLE")


@router.get("/{doc_id}/viewer-content")
async def get_doc_viewer_content(doc_id: str, citation_id: str = Query(...), user=Depends(require_current_user)):
    trace_id = make_trace_id()
    _resolve_document_for_user(doc_id, user)
    try:
        return ok(get_engine().get_document_viewer_content(user["user_id"], doc_id, citation_id), trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        _raise_conflict(str(exc), code="ORIGINAL_VIEW_UNAVAILABLE")


@router.get("/{doc_id}/detail")
async def get_doc_detail(doc_id: str, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    _resolve_document_for_user(doc_id, user)
    try:
        return ok(get_engine().get_document_detail(doc_id), trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("")
async def list_docs(kb_id: str, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    require_kb_read_access(user, kb_id)
    return ok({"items": get_engine().list_docs(kb_id)}, trace_id=trace_id)


@router.delete("/{doc_id}")
async def delete_doc(doc_id: str, user=Depends(require_current_user)):
    trace_id = make_trace_id()
    _resolve_document_for_write(doc_id, user)
    try:
        get_engine().delete_document(doc_id)
        return ok({"doc_id": doc_id, "deleted": True}, trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
