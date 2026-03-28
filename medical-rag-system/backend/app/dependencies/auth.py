from typing import Any, Dict, Optional

from fastapi import Cookie, Depends, HTTPException

from app.core.config import settings
from app.core.rag_engine import get_engine


def _resolve_user_from_cookie(auth_token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not auth_token:
        return None
    return get_engine().auth_service.get_current_user(auth_token)


def get_optional_current_user(
    auth_token: Optional[str] = Cookie(default=None, alias=settings.AUTH_COOKIE_NAME),
):
    return _resolve_user_from_cookie(auth_token)


def require_current_user(
    auth_token: Optional[str] = Cookie(default=None, alias=settings.AUTH_COOKIE_NAME),
):
    user = _resolve_user_from_cookie(auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    return user


def require_admin(user=Depends(require_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _resolve_kb_access(user: Dict[str, Any], kb_id: str) -> Dict[str, Any]:
    kb = get_engine().repo.get_knowledge_base(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    visibility = kb.get("visibility") or "system"
    is_admin = user.get("role") == "admin"
    owner_user_id = kb.get("owner_user_id")

    if visibility == "private":
        if owner_user_id != user.get("user_id"):
            raise HTTPException(status_code=404, detail="知识库不存在")
        kb["access_level"] = "write"
        return kb

    if kb.get("status") != "active" and not is_admin:
        raise HTTPException(status_code=404, detail="知识库不存在")

    kb["access_level"] = "write" if is_admin else "read"
    return kb


def require_kb_read_access(user: Dict[str, Any], kb_id: str) -> Dict[str, Any]:
    return _resolve_kb_access(user, kb_id)


def require_kb_write_access(user: Dict[str, Any], kb_id: str) -> Dict[str, Any]:
    kb = _resolve_kb_access(user, kb_id)
    if kb.get("access_level") != "write":
        raise HTTPException(status_code=403, detail="当前知识库无写入权限")
    return kb


def require_kb_read(kb_id: str, user=Depends(require_current_user)):
    return require_kb_read_access(user, kb_id)


def require_kb_write(kb_id: str, user=Depends(require_current_user)):
    return require_kb_write_access(user, kb_id)
