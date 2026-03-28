from fastapi import APIRouter, HTTPException, Request, Response

from app.core.config import settings
from app.core.rag_engine import get_engine
from app.core.security import auth_cookie_secure
from app.models.schemas import AuthLoginRequest, AuthRegisterRequest
from app.services import AuthConflictError, AuthForbiddenError, AuthUnauthorizedError
from app.utils.response import make_trace_id, ok


router = APIRouter()


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=auth_cookie_secure(),
        samesite="lax",
        max_age=settings.AUTH_SESSION_DAYS * 24 * 60 * 60,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=auth_cookie_secure(),
        samesite="lax",
    )


@router.post("/register")
async def register(payload: AuthRegisterRequest, response: Response):
    trace_id = make_trace_id()
    engine = get_engine()
    try:
        user, token = engine.auth_service.register(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
        _set_auth_cookie(response, token)
        return ok({"user": user, "default_kb_id": user.get("default_kb_id")}, trace_id=trace_id)
    except AuthConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login")
async def login(payload: AuthLoginRequest, response: Response):
    trace_id = make_trace_id()
    engine = get_engine()
    try:
        user, token = engine.auth_service.login(email=payload.email, password=payload.password)
        _set_auth_cookie(response, token)
        return ok({"user": user, "default_kb_id": user.get("default_kb_id")}, trace_id=trace_id)
    except AuthUnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except AuthForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/logout")
async def logout(request: Request, response: Response):
    trace_id = make_trace_id()
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if token:
        get_engine().auth_service.logout(token)
    _clear_auth_cookie(response)
    return ok({"success": True}, trace_id=trace_id)


@router.get("/me")
async def me(request: Request, response: Response):
    trace_id = make_trace_id()
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    user = get_engine().auth_service.get_current_user(token or "")
    if not user:
        _clear_auth_cookie(response)
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    return ok({"user": user, "default_kb_id": user.get("default_kb_id")}, trace_id=trace_id)
