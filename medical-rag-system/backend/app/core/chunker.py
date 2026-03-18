from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


CHUNK_STRATEGY_VERSION = "law_structured_v1"
ZH_NUMBER_PATTERN = r"[一二三四五六七八九十百千万零〇两0-9]+"
ARTICLE_HEADING_RE = re.compile(rf"^[ \t\u3000]*(第{ZH_NUMBER_PATTERN}条)\s*(.*)$", re.MULTILINE)
PART_HEADING_RE = re.compile(rf"^[ \t\u3000]*(第{ZH_NUMBER_PATTERN}编)\s*(.*)$", re.MULTILINE)
CHAPTER_HEADING_RE = re.compile(rf"^[ \t\u3000]*(第{ZH_NUMBER_PATTERN}章)\s*(.*)$", re.MULTILINE)
SECTION_HEADING_RE = re.compile(rf"^[ \t\u3000]*(第{ZH_NUMBER_PATTERN}节)\s*(.*)$", re.MULTILINE)
CLAUSE_RE = re.compile(rf"(第{ZH_NUMBER_PATTERN}款)")
ITEM_RE = re.compile(r"(（[一二三四五六七八九十百千万零〇两0-9]+）)")
LAW_TITLE_HINTS = ("法", "条例", "规定", "办法", "解释")


@dataclass
class HeadingEvent:
    kind: str
    label: str
    title: str
    start: int


@dataclass
class SemanticUnit:
    semantic_unit_id: str
    unit_kind: str
    start_pos: int
    end_pos: int
    text: str
    title_path: List[str]
    article_no: Optional[str] = None
    clause_no: Optional[str] = None
    item_no: Optional[str] = None


def chunk_text(
    text: str,
    chunk_size: int,
    overlap: int,
    doc_id: str,
    *,
    doc_type: str = "text",
    document_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk.size 必须大于 0")
    overlap = max(0, overlap)
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)

    document_meta = document_meta or {}
    source_fingerprint = str(document_meta.get("source_fingerprint") or f"legacy-{doc_id}")
    semantic_units = _build_semantic_units(text, document_meta)
    rows: List[Dict[str, Any]] = []

    for unit in semantic_units:
        windows = _split_unit_windows(unit.text, chunk_size, overlap)
        window_count = max(1, len(windows))
        for window_index, window in enumerate(windows):
            start_pos = unit.start_pos + window["start_pos"]
            end_pos = unit.start_pos + window["end_pos"]
            locator = build_locator(
                doc_type,
                document_meta,
                start_pos,
                end_pos,
                extra={
                    "unit_kind": unit.unit_kind,
                    "title_path": list(unit.title_path),
                    "article_no": unit.article_no,
                    "clause_no": window.get("clause_no") or unit.clause_no,
                    "item_no": window.get("item_no") or unit.item_no,
                    "semantic_unit_id": unit.semantic_unit_id,
                    "window_index": window_index,
                    "window_count": window_count,
                    "chunk_strategy_version": CHUNK_STRATEGY_VERSION,
                },
            )
            rows.append(
                {
                    "chunk_id": _build_chunk_id(
                        source_fingerprint,
                        unit.semantic_unit_id,
                        window_index,
                        window["chunk_text"],
                    ),
                    "doc_id": doc_id,
                    "chunk_index": len(rows),
                    "chunk_text": window["chunk_text"],
                    "start_pos": start_pos,
                    "end_pos": end_pos,
                    "section": _resolve_section(unit, window["chunk_text"]),
                    "article_no": unit.article_no or extract_article_no(window["chunk_text"]),
                    "page_start": locator.get("page_start"),
                    "page_end": locator.get("page_end"),
                    "locator_json": locator,
                }
            )
    return rows


def build_locator(
    doc_type: str,
    document_meta: Dict[str, Any],
    start: int,
    end: int,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if doc_type == "pdf":
        page_spans = document_meta.get("page_spans") or []
        overlaps = [span for span in page_spans if span.get("end", 0) > start and span.get("start", 0) < end]
        if overlaps:
            base = {"kind": "pdf", "page_start": int(overlaps[0]["page"]), "page_end": int(overlaps[-1]["page"])}
        else:
            base = {"kind": "pdf", "page_start": None, "page_end": None}
    elif doc_type == "docx":
        paragraph_spans = document_meta.get("paragraph_spans") or []
        overlaps = [span for span in paragraph_spans if span.get("end", 0) > start and span.get("start", 0) < end]
        if overlaps:
            base = {
                "kind": "docx",
                "paragraph_start": int(overlaps[0]["index"]),
                "paragraph_end": int(overlaps[-1]["index"]),
            }
        else:
            base = {"kind": "docx", "paragraph_start": None, "paragraph_end": None}
    else:
        base = {"kind": "text"}

    base["start_pos"] = start
    base["end_pos"] = end
    if extra:
        base.update(extra)
    return base


def extract_section(text: str) -> Optional[str]:
    match = re.search(rf"(第{ZH_NUMBER_PATTERN}[章节编])", text)
    return match.group(1) if match else None


def extract_article_no(text: str) -> Optional[str]:
    match = re.search(rf"(第{ZH_NUMBER_PATTERN}条)", text)
    return match.group(1) if match else None


def _build_semantic_units(text: str, document_meta: Dict[str, Any]) -> List[SemanticUnit]:
    article_matches = list(ARTICLE_HEADING_RE.finditer(text))
    if _is_law_like_document(text, document_meta, article_matches):
        units = _build_law_units(text, article_matches)
        if units:
            return units
    return _build_generic_units(text)


def _is_law_like_document(text: str, document_meta: Dict[str, Any], article_matches: List[re.Match[str]]) -> bool:
    if len(article_matches) >= 3:
        return True

    title_candidates = [
        str(document_meta.get("title") or ""),
        str(document_meta.get("original_file_name") or ""),
    ]
    title = " ".join(title_candidates)
    if len(article_matches) >= 1 and any(hint in title for hint in LAW_TITLE_HINTS):
        return True

    return len(article_matches) >= 2 and text.count("条") >= 4


def _build_law_units(text: str, article_matches: List[re.Match[str]]) -> List[SemanticUnit]:
    heading_events = _collect_heading_events(text)
    heading_index = 0
    heading_state: Dict[str, Optional[str]] = {"part": None, "chapter": None, "section": None}
    units: List[SemanticUnit] = []

    for idx, match in enumerate(article_matches):
        article_start = match.start()
        next_start = article_matches[idx + 1].start() if idx + 1 < len(article_matches) else len(text)
        while heading_index < len(heading_events) and heading_events[heading_index].start < article_start:
            _apply_heading_event(heading_state, heading_events[heading_index])
            heading_index += 1

        trimmed = _trim_span(text, article_start, next_start)
        if not trimmed:
            continue

        article_no = match.group(1)
        article_text = trimmed["text"]
        title_path = _title_path_from_state(heading_state)
        semantic_unit_id = f"article::{article_no}"
        units.append(
            SemanticUnit(
                semantic_unit_id=semantic_unit_id,
                unit_kind="article",
                start_pos=trimmed["start_pos"],
                end_pos=trimmed["end_pos"],
                text=article_text,
                title_path=title_path,
                article_no=article_no,
                clause_no=_extract_first_clause(article_text),
                item_no=_extract_first_item(article_text),
            )
        )
    return units


def _build_generic_units(text: str) -> List[SemanticUnit]:
    trimmed = _trim_span(text, 0, len(text))
    if not trimmed:
        return []
    return [
        SemanticUnit(
            semantic_unit_id="generic::full_text",
            unit_kind="generic",
            start_pos=trimmed["start_pos"],
            end_pos=trimmed["end_pos"],
            text=trimmed["text"],
            title_path=[],
        )
    ]


def _split_unit_windows(text: str, chunk_size: int, overlap: int) -> List[Dict[str, Any]]:
    if len(text) <= chunk_size:
        clause_no = _extract_first_clause(text)
        item_no = _extract_first_item(text)
        return [{"start_pos": 0, "end_pos": len(text), "chunk_text": text, "clause_no": clause_no, "item_no": item_no}]

    step = max(1, chunk_size - overlap)
    windows: List[Dict[str, Any]] = []
    for start in range(0, len(text), step):
        end = min(len(text), start + chunk_size)
        trimmed = _trim_relative_span(text, start, end)
        if not trimmed:
            continue
        chunk_text = trimmed["text"]
        windows.append(
            {
                "start_pos": trimmed["start_pos"],
                "end_pos": trimmed["end_pos"],
                "chunk_text": chunk_text,
                "clause_no": _extract_first_clause(chunk_text),
                "item_no": _extract_first_item(chunk_text),
            }
        )
        if end >= len(text):
            break
    return windows


def _collect_heading_events(text: str) -> List[HeadingEvent]:
    events: List[HeadingEvent] = []
    for kind, pattern in (
        ("part", PART_HEADING_RE),
        ("chapter", CHAPTER_HEADING_RE),
        ("section", SECTION_HEADING_RE),
    ):
        for match in pattern.finditer(text):
            events.append(
                HeadingEvent(
                    kind=kind,
                    label=match.group(1),
                    title=(match.group(2) or "").strip(),
                    start=match.start(),
                )
            )
    events.sort(key=lambda item: item.start)
    return events


def _apply_heading_event(state: Dict[str, Optional[str]], event: HeadingEvent) -> None:
    label = event.label if not event.title else f"{event.label} {event.title}"
    if event.kind == "part":
        state["part"] = label
        state["chapter"] = None
        state["section"] = None
    elif event.kind == "chapter":
        state["chapter"] = label
        state["section"] = None
    elif event.kind == "section":
        state["section"] = label


def _title_path_from_state(state: Dict[str, Optional[str]]) -> List[str]:
    return [value for value in (state.get("part"), state.get("chapter"), state.get("section")) if value]


def _resolve_section(unit: SemanticUnit, chunk_text: str) -> Optional[str]:
    if unit.title_path:
        return unit.title_path[-1]
    return extract_section(chunk_text)


def _extract_first_clause(text: str) -> Optional[str]:
    match = CLAUSE_RE.search(text)
    return match.group(1) if match else None


def _extract_first_item(text: str) -> Optional[str]:
    match = ITEM_RE.search(text)
    return match.group(1) if match else None


def _trim_span(text: str, start: int, end: int) -> Optional[Dict[str, Any]]:
    if start >= end:
        return None
    raw = text[start:end]
    stripped = raw.strip()
    if not stripped:
        return None

    left_offset = len(raw) - len(raw.lstrip())
    right_offset = len(raw.rstrip())
    return {
        "start_pos": start + left_offset,
        "end_pos": start + right_offset,
        "text": stripped,
    }


def _trim_relative_span(text: str, start: int, end: int) -> Optional[Dict[str, Any]]:
    trimmed = _trim_span(text, start, end)
    if trimmed is None:
        return None
    return {
        "start_pos": trimmed["start_pos"],
        "end_pos": trimmed["end_pos"],
        "text": trimmed["text"],
    }


def _build_chunk_id(source_fingerprint: str, semantic_unit_id: str, window_index: int, chunk_text: str) -> str:
    normalized_text_hash = hashlib.sha1(chunk_text.strip().encode("utf-8")).hexdigest()[:16]
    raw = f"{source_fingerprint}|{semantic_unit_id}|{window_index}|{normalized_text_hash}"
    return f"chk_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"
