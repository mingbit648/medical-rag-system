from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.rag_engine import engine
from app.models.schemas import IndexRequest
from app.utils.response import make_trace_id, ok


router = APIRouter()


def _raise_conflict(message: str, *, code: str) -> None:
    raise HTTPException(status_code=409, detail={"code": code, "message": message})


@router.post("/import")
async def import_doc(
    file: UploadFile = File(...),
    source_url: Optional[str] = Form(default=None),
    doc_type: Optional[str] = Form(default=None),
):
    trace_id = make_trace_id()
    try:
        content = await file.read()
        if not content:
            raise ValueError("上传文件为空。")
        result = engine.import_document(
            file_name=file.filename or "uploaded_file",
            content=content,
            doc_type=doc_type,
            source_url=source_url,
        )
        return ok(result, trace_id=trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{doc_id}/index")
async def index_doc(doc_id: str, request: IndexRequest):
    trace_id = make_trace_id()
    try:
        result = engine.build_index(
            doc_id=doc_id,
            chunk_size=request.chunk.size,
            overlap=request.chunk.overlap,
            bm25_enabled=request.bm25.enabled,
            vector_enabled=request.vector.enabled,
            embed_model=request.vector.embed_model,
        )
        return ok(result, trace_id=trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{doc_id}/status")
async def get_doc_status(doc_id: str):
    trace_id = make_trace_id()
    try:
        return ok(engine.get_doc_status(doc_id), trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{doc_id}/file")
async def get_doc_file(doc_id: str):
    try:
        result = engine.get_document_file(doc_id)
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
async def get_doc_viewer_content(doc_id: str, citation_id: str = Query(...)):
    trace_id = make_trace_id()
    try:
        return ok(engine.get_document_viewer_content(doc_id, citation_id), trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        _raise_conflict(str(exc), code="ORIGINAL_VIEW_UNAVAILABLE")


@router.get("")
async def list_docs():
    trace_id = make_trace_id()
    return ok({"items": engine.list_docs()}, trace_id=trace_id)


@router.delete("/{doc_id}")
async def delete_doc(doc_id: str):
    trace_id = make_trace_id()
    try:
        engine.delete_document(doc_id)
        return ok({"doc_id": doc_id, "deleted": True}, trace_id=trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
