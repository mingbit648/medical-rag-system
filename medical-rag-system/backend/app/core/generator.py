"""RAG 生成模块：LLM 调用、Prompt 组装、引用构建。"""

import json
import logging
import uuid
from typing import Any, Dict, List

import httpx

from app.core.config import settings
from app.core.session_context import build_prompt_history
from .text_utils import DISCLAIMER, SYSTEM_PROMPT, now_iso

logger = logging.getLogger(__name__)


def make_citation(repo, hit: Dict[str, Any], persist: bool = True, message_id: str | None = None) -> Dict[str, Any]:
    doc = repo.get_document(hit["doc_id"])
    if doc is None:
        raise KeyError("引用对应文档不存在")

    citation_id = f"c_{uuid.uuid4().hex[:10]}"
    data = {
        "citation_id": citation_id,
        "chunk_id": hit["chunk_id"],
        "doc_id": hit["doc_id"],
        "source": {"title": doc["title"], "url_or_file": doc["source_url"] or doc.get("original_file_name") or doc["file_name"]},
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
        repo.save_citation(citation_id, hit["chunk_id"], hit["doc_id"], data, now_iso(), message_id=message_id)
    return data


def history_for_prompt(
    history_messages: List[Dict[str, Any]],
    *,
    summary_text: str = "",
) -> List[Dict[str, str]]:
    if not history_messages:
        return build_prompt_history(summary_text, [], recent_limit=settings.HISTORY_PROMPT_MESSAGES)
    return build_prompt_history(
        summary_text,
        history_messages,
        recent_limit=settings.HISTORY_PROMPT_MESSAGES,
    )


def build_evidence_text(citation_like: List[Dict[str, Any]]) -> str:
    evidence_lines = []
    for i, item in enumerate(citation_like[:8], start=1):
        source = item.get("source", {})
        title = source.get("title", "未知来源")
        snippet = item.get("snippet") or item.get("chunk_text", "")
        evidence_lines.append(f"[{i}] {title}: {snippet}")
    return "\n".join(evidence_lines)


def build_user_prompt(query: str, citation_like: List[Dict[str, Any]]) -> str:
    if citation_like:
        evidence_text = build_evidence_text(citation_like)
        return (
            f"用户问题：{query}\n\n"
            "以下是知识库检索到的相关法律资料片段，请优先依据这些内容作答：\n"
            f"{evidence_text}\n\n"
            "输出要求：\n"
            "1) 先直接回答用户问题，再分点说明理由、风险和建议；\n"
            "2) 有知识库依据的结论，请使用[1][2]这类编号标注；\n"
            "3) 如果某部分超出了检索证据支持范围，要明确说明该部分属于基于一般法律知识的审慎分析；\n"
            f"4) 结尾附上这句话：{DISCLAIMER}"
        )

    return (
        f"用户问题：{query}\n\n"
        "当前知识库没有检索到可直接引用的相关法律片段。\n"
        "请继续正常回答，但必须遵守以下要求：\n"
        "1) 可以基于一般法律知识给出谨慎、清晰、可执行的分析和建议；\n"
        "2) 明确说明当前回答未基于知识库命中结果，结论可能因地区规定、案件事实和最新规则而变化；\n"
        "3) 不要编造具体法条编号、案例名称、裁判结果或确定性结论；\n"
        "4) 优先提示用户需要补充的关键事实、可行的下一步，以及在必要时咨询律师、劳动监察或仲裁机构；\n"
        "5) 不要使用[1][2]这类知识库引用编号；\n"
        f"6) 结尾附上这句话：{DISCLAIMER}"
    )


def mock_answer(query: str, citation_like: List[Dict[str, Any]]) -> str:
    if not citation_like:
        return (
            f"当前知识库未检索到与“{query}”直接相关的法律片段，但仍可以先按一般法律咨询思路处理。\n\n"
            "建议先补充或核实以下关键信息：争议发生时间、所在地区、双方身份关系、现有证据材料、你的核心诉求，以及对方目前的处理态度。"
            "在此基础上，再判断应优先协商、投诉、申请仲裁或诉讼，还是先固定证据。\n\n"
            "如果你继续补充案情细节，我可以把问题进一步拆解成更具体的处理建议。\n\n"
            f"> {DISCLAIMER}"
        )

    lines = [f"基于当前检索证据，关于“{query}”可先参考："]
    for i, item in enumerate(citation_like[:3], start=1):
        snippet = item.get("snippet") or item.get("chunk_text", "")
        lines.append(f"{i}. {snippet[:120]}...[{i}]")
    lines.append("")
    lines.append(f"> {DISCLAIMER}")
    return "\n".join(lines)


def call_openai_compatible_llm(messages: List[Dict[str, str]], llm_cfg: Dict[str, Any]) -> str:
    api_key = (llm_cfg.get("api_key") or settings.DEEPSEEK_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY（或请求中的 llm.api_key）")

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

    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                if not data_str:
                    continue
                try:
                    chunk_json = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = chunk_json.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content


def generate_answer(
    query: str,
    citation_like: List[Dict[str, Any]],
    llm: Dict[str, Any],
    history_messages: List[Dict[str, Any]],
    summary_text: str = "",
) -> str:
    provider = (llm.get("provider") or settings.LLM_PROVIDER or "mock").strip().lower()
    if provider in {"mock", "simple-local", "local"}:
        return mock_answer(query, citation_like)

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history_for_prompt(history_messages, summary_text=summary_text))
    messages.append({"role": "user", "content": build_user_prompt(query, citation_like)})

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
    summary_text: str = "",
):
    provider = (llm.get("provider") or settings.LLM_PROVIDER or "mock").strip().lower()
    if provider in {"mock", "simple-local", "local"}:
        yield mock_answer(query, citation_like)
        return

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history_for_prompt(history_messages, summary_text=summary_text))
    messages.append({"role": "user", "content": build_user_prompt(query, citation_like)})

    try:
        answer_parts = []
        async for chunk in call_openai_compatible_llm_stream(messages, llm):
            answer_parts.append(chunk)
            yield chunk

        full_answer = "".join(answer_parts)
        if DISCLAIMER not in full_answer:
            yield f"\n\n> {DISCLAIMER}"
    except Exception as exc:
        logger.warning("真实 LLM 流式调用失败，降级为 mock 生成: %s", exc)
        yield mock_answer(query, citation_like)
