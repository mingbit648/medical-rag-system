"""文本处理工具函数和数据类。"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List, Optional

import numpy as np

DISCLAIMER = "仅供学习与辅助检索，不构成法律意见。"
PRONOUN_REF_PATTERN = re.compile(r"(这(个|种|条|些)|那(个|种|条|些)|其|该|上述|前面|它|他|她)")
SYSTEM_PROMPT = (
    "你是一名法律咨询助手，擅长劳动争议及常见民商事法律问题的分析。"
    "优先依据知识库检索到的法律资料、法条片段和已给出的上下文作答，并在有证据时尽量标注引用编号，例如[1][2]。"
    "如果知识库证据不足或没有检索到相关片段，仍要继续给出谨慎、清晰、可执行的回答，但必须明确说明该部分未得到当前知识库证据支持。"
    "不得编造具体法条编号、司法案例、裁判结果或其他未经提供的法律依据。"
    "对不确定事项要说明前提条件、潜在风险、需要补充的事实信息，以及建议的下一步处理路径。"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tokenize(text: str) -> List[str]:
    return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+", text.lower())


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(html_text: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    return clean_text(text)


def extract_title(filename: str, text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:80] if first_line else filename


def l2_normalize_rows(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-8, norms)
    return matrix / norms


@dataclass
class ChunkRecord:
    chunk_id: str
    doc_id: str
    chunk_index: int
    chunk_text: str
    start_pos: int
    end_pos: int
    section: Optional[str] = None
    article_no: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    locator_json: Optional[Dict[str, Any]] = None
