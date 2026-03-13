"""文本分块逻辑。"""

import re
import uuid
from typing import Any, Dict, List, Optional


def chunk_text(text: str, chunk_size: int, overlap: int, doc_id: str) -> List[Dict[str, Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk.size 必须大于 0")
    overlap = max(0, overlap)
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)
    step = max(1, chunk_size - overlap)

    rows: List[Dict[str, Any]] = []
    idx = 0
    for start in range(0, len(text), step):
        end = min(len(text), start + chunk_size)
        body = text[start:end].strip()
        if not body:
            continue
        rows.append(
            {
                "chunk_id": f"chk_{uuid.uuid4().hex[:14]}",
                "doc_id": doc_id,
                "chunk_index": idx,
                "chunk_text": body,
                "start_pos": start,
                "end_pos": end,
                "section": extract_section(body),
                "article_no": extract_article_no(body),
                "page_start": None,
                "page_end": None,
            }
        )
        idx += 1
        if end >= len(text):
            break
    return rows


def extract_section(text: str) -> Optional[str]:
    m = re.search(r"(第[一二三四五六七八九十百千0-9]+[章节编])", text)
    return m.group(1) if m else None


def extract_article_no(text: str) -> Optional[str]:
    m = re.search(r"(第[一二三四五六七八九十百千0-9]+条)", text)
    return m.group(1) if m else None
