import uuid
from typing import Any, Dict, Optional


def make_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:16]}"


def ok(data: Dict[str, Any], message: str = "ok", trace_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "trace_id": trace_id or make_trace_id(),
    }
