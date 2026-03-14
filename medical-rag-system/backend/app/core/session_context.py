from typing import Any, Dict, List


def normalize_text(value: str, max_chars: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def build_session_summary(
    messages: List[Dict[str, Any]],
    *,
    max_chars: int,
    max_user_items: int,
    max_assistant_items: int,
    item_chars: int,
) -> str:
    # Assistant output is intentionally excluded from long-term memory to avoid
    # reinforcing speculative or incorrect model inferences across turns.
    _ = max_assistant_items
    user_items: List[str] = []
    seen_user = set()

    for msg in messages:
        role = msg.get("role")
        content = normalize_text(msg.get("content") or "", item_chars)
        if not content:
            continue
        if role == "user" and len(user_items) < max_user_items and content not in seen_user:
            user_items.append(content)
            seen_user.add(content)

    sections: List[str] = []
    if user_items:
        sections.append("用户已提供的背景与诉求:\n" + "\n".join(f"- {item}" for item in user_items))

    summary = "\n\n".join(sections)
    return normalize_text(summary, max_chars) if summary else ""


def build_prompt_history(
    summary_text: str,
    recent_messages: List[Dict[str, Any]],
    *,
    recent_limit: int,
) -> List[Dict[str, str]]:
    prompt_messages: List[Dict[str, str]] = []

    if summary_text:
        prompt_messages.append(
            {
                "role": "system",
                "content": (
                    "以下是当前会话的压缩摘要，仅用于保持上下文连续性。"
                    "不要把其中未确认的推断当作既定事实。\n"
                    f"{summary_text}"
                ),
            }
        )

    candidates = recent_messages[-recent_limit:]
    for msg in candidates:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        prompt_messages.append({"role": role, "content": content})

    return prompt_messages


def build_retrieval_query(
    query: str,
    *,
    summary_text: str,
    recent_messages: List[Dict[str, Any]],
    short_query_chars: int,
    max_recent_user_messages: int,
    pronoun_pattern,
) -> str:
    raw_query = (query or "").strip()
    if not raw_query:
        return raw_query

    need_context = len(raw_query) <= short_query_chars or bool(pronoun_pattern.search(raw_query))
    if not need_context:
        return raw_query

    recent_user_messages = [
        normalize_text(msg.get("content") or "", 180)
        for msg in recent_messages
        if msg.get("role") == "user" and (msg.get("content") or "").strip()
    ]
    recent_user_messages = recent_user_messages[-max_recent_user_messages:]

    parts: List[str] = []
    if summary_text:
        parts.append(f"会话摘要:\n{normalize_text(summary_text, 320)}")
    if recent_user_messages:
        parts.append("最近用户问题:\n" + "\n".join(f"- {item}" for item in recent_user_messages))
    parts.append(f"当前问题:\n{raw_query}")

    return "\n\n".join(parts) if len(parts) > 1 else raw_query
