import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.security import (
    build_session_expiry,
    create_session_token,
    hash_password,
    hash_session_token,
    normalize_email,
    verify_password,
)
from app.core.text_utils import now_iso
from app.repositories import PgRepository


logger = logging.getLogger(__name__)


class AuthError(RuntimeError):
    pass


class AuthConflictError(AuthError):
    pass


class AuthUnauthorizedError(AuthError):
    pass


class AuthForbiddenError(AuthError):
    pass


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class AuthService:
    def __init__(self, repo: PgRepository):
        self.repo = repo

    def ensure_bootstrap_admin(self) -> Dict[str, Any]:
        admin_email = normalize_email(settings.BOOTSTRAP_ADMIN_EMAIL)
        admin_password = settings.BOOTSTRAP_ADMIN_PASSWORD.strip()
        display_name = (settings.BOOTSTRAP_ADMIN_DISPLAY_NAME or "系统管理员").strip() or "系统管理员"

        users = self.repo.list_users()
        existing_admin = next((item for item in users if item.get("role") == "admin"), None)
        if existing_admin:
            return self._public_user(existing_admin)

        if not admin_email or not admin_password:
            raise RuntimeError("缺少 BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD，无法初始化管理员。")

        existing = self.repo.get_user_by_email(admin_email)
        if existing:
            if existing.get("role") != "admin":
                raise RuntimeError("bootstrap 管理员邮箱已存在，但角色不是 admin。")
            user = existing
        else:
            now = now_iso()
            user = self.repo.create_user(
                user_id=f"user_{uuid.uuid4().hex[:12]}",
                email=admin_email,
                password_hash=hash_password(admin_password),
                display_name=display_name,
                role="admin",
                status="active",
                created_at=now,
                updated_at=now,
            )
            logger.info("bootstrap admin created: %s", admin_email)
        return self._public_user(user)

    def create_system_knowledge_base(self, admin_user_id: str) -> Dict[str, Any]:
        existing = self.repo.get_knowledge_base_by_name(settings.DEFAULT_KB_NAME, owner_user_id=None, visibility="system")
        if existing:
            return existing
        now = now_iso()
        kb = self.repo.create_knowledge_base(
            kb_id=f"kb_{uuid.uuid4().hex[:12]}",
            name=settings.DEFAULT_KB_NAME,
            description=settings.DEFAULT_KB_DESCRIPTION,
            status="active",
            created_by=admin_user_id,
            owner_user_id=None,
            visibility="system",
            is_default=False,
            created_at=now,
            updated_at=now,
        )
        logger.info("system knowledge base created: %s", kb["kb_id"])
        return kb

    def create_default_private_knowledge_base(self, user_id: str) -> Dict[str, Any]:
        existing = self.repo.get_default_private_knowledge_base(user_id)
        if existing:
            return existing

        base_name = settings.PRIVATE_DEFAULT_KB_NAME.strip() or "我的知识库"
        candidate = base_name
        suffix = 2
        while self.repo.get_knowledge_base_by_name(candidate, owner_user_id=user_id, visibility="private"):
            candidate = f"{base_name}{suffix}"
            suffix += 1

        now = now_iso()
        return self.repo.create_knowledge_base(
            kb_id=f"kb_{uuid.uuid4().hex[:12]}",
            name=candidate,
            description=settings.PRIVATE_DEFAULT_KB_DESCRIPTION,
            status="active",
            created_by=user_id,
            owner_user_id=user_id,
            visibility="private",
            is_default=True,
            created_at=now,
            updated_at=now,
        )

    def migrate_legacy_data(self, *, system_kb_id: str, admin_user_id: str) -> None:
        self.repo.migrate_legacy_ownership(system_kb_id=system_kb_id, admin_user_id=admin_user_id)

    def register(self, *, email: str, password: str, display_name: Optional[str]) -> tuple[Dict[str, Any], str]:
        normalized_email = normalize_email(email)
        if not normalized_email:
            raise AuthError("email 不能为空")
        if self.repo.get_user_by_email(normalized_email):
            raise AuthConflictError("该邮箱已注册")

        now = now_iso()
        user = self.repo.create_user(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            email=normalized_email,
            password_hash=hash_password(password),
            display_name=(display_name or "").strip() or None,
            role="user",
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.create_default_private_knowledge_base(user["user_id"])
        raw_token = self._issue_auth_session(user["user_id"])
        logger.info("user registered: %s", normalized_email)
        return self._public_user(user), raw_token

    def login(self, *, email: str, password: str) -> tuple[Dict[str, Any], str]:
        normalized_email = normalize_email(email)
        user = self.repo.get_user_by_email(normalized_email)
        if not user or not verify_password(password, user.get("password_hash", "")):
            raise AuthUnauthorizedError("邮箱或密码错误")
        if user.get("status") != "active":
            raise AuthForbiddenError("账号已被禁用")

        raw_token = self._issue_auth_session(user["user_id"])
        logger.info("user login: %s", normalized_email)
        return self._public_user(user), raw_token

    def logout(self, raw_token: str) -> None:
        token_hash = hash_session_token(raw_token)
        auth_session = self.repo.get_auth_session_by_token_hash(token_hash)
        if auth_session:
            self.repo.delete_auth_session(auth_session["auth_session_id"])
            logger.info("user logout: %s", auth_session["user_id"])

    def get_current_user(self, raw_token: str) -> Optional[Dict[str, Any]]:
        if not raw_token:
            return None
        self.repo.delete_expired_auth_sessions(now_iso())
        token_hash = hash_session_token(raw_token)
        auth_session = self.repo.get_auth_session_by_token_hash(token_hash)
        if not auth_session:
            return None
        if _parse_datetime(auth_session["expires_at"]) <= datetime.now(timezone.utc):
            self.repo.delete_auth_session(auth_session["auth_session_id"])
            return None

        user = self.repo.get_user(auth_session["user_id"])
        if not user or user.get("status") != "active":
            self.repo.delete_auth_session(auth_session["auth_session_id"])
            return None

        self.repo.touch_auth_session(
            auth_session["auth_session_id"],
            last_seen_at=now_iso(),
            expires_at=build_session_expiry().isoformat(),
        )
        return self._public_user(user)

    def _issue_auth_session(self, user_id: str) -> str:
        now = now_iso()
        expires_at = build_session_expiry()
        raw_token = create_session_token()
        self.repo.create_auth_session(
            auth_session_id=f"as_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            session_token_hash=hash_session_token(raw_token),
            expires_at=expires_at.isoformat(),
            created_at=now,
            last_seen_at=now,
        )
        return raw_token

    def _public_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        default_kb = self.repo.get_default_accessible_knowledge_base(user["user_id"])
        return {
            "user_id": user["user_id"],
            "email": user["email"],
            "display_name": user.get("display_name"),
            "role": user.get("role", "user"),
            "status": user.get("status", "active"),
            "default_kb_id": default_kb.get("kb_id") if default_kb else None,
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
        }
