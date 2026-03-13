"""RAG 生成模块：LLM 调用、Prompt 组装、引用构建。"""

import logging
import uuid
from typing import Any, Dict, List

import httpx

from app.core.config import settings
from .text_utils import DISCLAIMER, SYSTEM_PROMPT, now_iso

logger = logging.getLogger(__name__)


def make_citation(repo, hit: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    doc = repo.get_document(hit["doc_id"])
    if doc is None:
        raise KeyError("引用对应文档不存在")

    citation_id = f"c_{uuid.uuid4().hex[:10]}"
    data = {
        "citation_id": citation_id,
        "chunk_id": hit["chunk_id"],
        "doc_id": hit["doc_id"],
        "source": {"title": doc["title"], "url_or_file": doc["source_url"] or doc["file_name"]},
        "location": {
            "page": hit.get("page_start"),
            "section": hit.get("section"),
            "article_no": hit.get("article_no"),
        },
        "snippet": hit["chunk_text"][:260],
        "scores": {
            "bm25": round(float(hit["bm25"]), 4),
            "vector": round(float(hit["vector"]), 4),
            "rrf": round(float(hit["rrf"]), 6),
            "rerank": round(float(hit["rerank"]), 4),
        },
    }
    if persist:
        repo.save_citation(citation_id, hit["chunk_id"], hit["doc_id"], data, now_iso())
    return data


def history_for_prompt(history_messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not history_messages:
        return []
    candidates = history_messages[-settings.HISTORY_PROMPT_MESSAGES:]
    prepared: List[Dict[str, str]] = []
    for msg in candidates:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        prepared.append({"role": role, "content": content})
    return prepared


def mock_answer(query: str, citation_like: List[Dict[str, Any]]) -> str:
    if not citation_like:
        return f"未检索到可用证据，建议补充更具体的问题描述。\n\n> {DISCLAIMER}"

    lines = [f"基于当前检索证据，关于'{query}'可先参考："]
    for i, item in enumerate(citation_like[:3], start=1):
        snippet = item.get("snippet") or item.get("chunk_text", "")
        lines.append(f"{i}. {snippet[:120]}...[{i}]")
    lines.append("")
    lines.append(f"> {DISCLAIMER}")
    return "\n".join(lines)


def call_openai_compatible_llm(messages: List[Dict[str, str]], llm_cfg: Dict[str, Any]) -> str:
    api_key = (llm_cfg.get("api_key") or settings.DEEPSEEK_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY（或请求中 llm.api_key）")

    base_url = (llm_cfg.get("base_url") or settings.DEEPSEEK_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise RuntimeError("未配置 llm base_url")
    if base_url.endswith("/chat/completions"):
        endpoint = base_url
    elif base_url.endswith("/v1"):
        endpoint = f"{base_url}/chat/completions"
    else:
        endpoint = f"{base_url}/chat/completions"

    payload = {
        "model": llm_cfg.get("model") or settings.DEFAULT_LLM_MODEL,
        "messages": messages,
        "temperature": llm_cfg.get("temperature", 0.2),
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = ""
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            parts = []
            for item in raw_content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
            content = "".join(parts)
    if not content:
        raise RuntimeError("LLM 返回空内容")
    return content.strip()


async def call_openai_compatible_llm_stream(messages: List[Dict[str, str]], llm_cfg: Dict[str, Any]):
    api_key = (llm_cfg.get("api_key") or settings.DEEPSEEK_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")

    base_url = (llm_cfg.get("base_url") or settings.DEEPSEEK_BASE_URL).strip().rstrip("/")
    if base_url.endswith("/chat/completions"):
        endpoint = base_url
    elif base_url.endswith("/v1"):
        endpoint = f"{base_url}/chat/completions"
    else:
        endpoint = f"{base_url}/chat/completions"

    payload = {
        "model": llm_cfg.get("model") or settings.DEFAULT_LLM_MODEL,
        "messages": messages,
        "temperature": llm_cfg.get("temperature", 0.2),
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    import json
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    if not data_str:
                        continue
                    try:
                        chunk_json = json.loads(data_str)
                        choices = chunk_json.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue



def generate_answer(
    query: str,
    citation_like: List[Dict[str, Any]],
    llm: Dict[str, Any],
    history_messages: List[Dict[str, Any]],
) -> str:
    if not citation_like:
        return f"未检索到可用证据，建议补充更具体的问题描述。\n\n> {DISCLAIMER}"

    provider = (llm.get("provider") or settings.LLM_PROVIDER or "mock").strip().lower()
    if provider in {"mock", "simple-local", "local"}:
        return mock_answer(query, citation_like)

    evidence_lines = []
    for i, item in enumerate(citation_like[:8], start=1):
        source = item.get("source", {})
        title = source.get("title", "未知来源")
        snippet = item.get("snippet") or item.get("chunk_text", "")
        evidence_lines.append(f"[{i}] {title}: {snippet}")
    evidence_text = "\n".join(evidence_lines)

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history_for_prompt(history_messages))
    messages.append(
        {
            "role": "user",
            "content": (
                f"用户问题：{query}\n\n"
                "请基于以下检索证据作答：\n"
                f"{evidence_text}\n\n"
                "输出要求：\n"
                "1) 先给结论，再给依据；\n"
                "2) 用 [1][2] 标出依据；\n"
                f"3) 末尾附上这句话：{DISCLAIMER}"
            ),
        }
    )

    try:
        answer = call_openai_compatible_llm(messages, llm)
    except Exception as exc:
        logger.warning("真实 LLM 调用失败，降级为 mock 生成: %s", exc)
        answer = mock_answer(query, citation_like)

    if DISCLAIMER not in answer:
        answer = f"{answer}\n\n> {DISCLAIMER}"
    return answer


async def generate_answer_stream(
    query: str,
    citation_like: List[Dict[str, Any]],
    llm: Dict[str, Any],
    history_messages: List[Dict[str, Any]],
):
    if not citation_like:
        yield f"未检索到可用证据，建议补充更具体的问题描述。\n\n> {DISCLAIMER}"
        return

    provider = (llm.get("provider") or settings.LLM_PROVIDER or "mock").strip().lower()
    if provider in {"mock", "simple-local", "local"}:
        yield mock_answer(query, citation_like)
        return

    evidence_lines = []
    for i, item in enumerate(citation_like[:8], start=1):
        source = item.get("source", {})
        title = source.get("title", "未知来源")
        snippet = item.get("snippet") or item.get("chunk_text", "")
        evidence_lines.append(f"[{i}] {title}: {snippet}")
    evidence_text = "\n".join(evidence_lines)

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history_for_prompt(history_messages))
    messages.append(
        {
            "role": "user",
            "content": (
                f"用户问题：{query}\n\n"
                "请基于以下检索证据作答：\n"
                f"{evidence_text}\n\n"
                "输出要求：\n"
                "1) 先给结论，再给依据；\n"
                "2) 用 [1][2] 标出依据；\n"
                f"3) 末尾附上这句话：{DISCLAIMER}"
            ),
        }
    )

    try:
        answer_parts = []
        async for chunk in call_openai_compatible_llm_stream(messages, llm):
            answer_parts.append(chunk)
            yield chunk
        
        full_answer = "".join(answer_parts)
        if DISCLAIMER not in full_answer:
            yield f"\n\n> {DISCLAIMER}"
    except Exception as exc:
        logger.warning("真实 LLM 调用流式失败，降级为 mock 生成: %s", exc)
        yield mock_answer(query, citation_like)
