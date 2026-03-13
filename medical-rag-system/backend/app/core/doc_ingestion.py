"""文档导入：类型推断、文本提取。"""

import io
import uuid
from typing import Any, Dict, List, Optional

from .text_utils import clean_text, extract_title, now_iso, strip_html


def guess_doc_type(file_name: str) -> str:
    lower = file_name.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".html") or lower.endswith(".htm"):
        return "html"
    if lower.endswith(".docx"):
        return "docx"
    return "text"


def extract_text(content: bytes, doc_type: str) -> str:
    if doc_type == "pdf":
        try:
            import fitz  # type: ignore

            pages: List[str] = []
            with fitz.open(stream=content, filetype="pdf") as pdf:
                for page in pdf:
                    pages.append(page.get_text("text"))
            return "\n".join(pages)
        except Exception:
            return content.decode("utf-8", errors="ignore")

    if doc_type == "docx":
        try:
            from docx import Document  # type: ignore

            doc = Document(io.BytesIO(content))
            paragraphs: List[str] = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    paragraphs.append(text)
            return "\n".join(paragraphs)
        except Exception:
            return content.decode("utf-8", errors="ignore")

    raw = content.decode("utf-8", errors="ignore")
    if doc_type == "html":
        return strip_html(raw)
    return raw


def import_document(
    repo,
    file_name: str,
    content: bytes,
    doc_type: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_type = (doc_type or guess_doc_type(file_name)).lower()
    text = extract_text(content, resolved_type)
    if not text.strip():
        raise ValueError("文档解析后为空，请检查文件格式。")

    text = clean_text(text)
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    title = extract_title(file_name, text)
    payload = {
        "doc_id": doc_id,
        "title": title,
        "doc_type": resolved_type,
        "source_url": source_url,
        "file_name": file_name,
        "text": text,
        "created_at": now_iso(),
        "parse_status": "imported",
        "chunks": 0,
    }
    repo.upsert_document(payload)
    return {"doc_id": doc_id, "title": title, "doc_type": resolved_type, "status": "imported"}
