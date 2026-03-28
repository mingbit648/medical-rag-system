from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.rag_engine import get_engine
from app.routers import auth, chat, citations, docs, experiments, knowledge_bases, retrieve


def _cors_allow_origins() -> list[str]:
    raw = (settings.CORS_ALLOW_ORIGINS or "").strip()
    if not raw:
        return []
    if raw == "*":
        raise RuntimeError("认证接口启用 Cookie Session 时，CORS_ALLOW_ORIGINS 不能配置为 *")
    return [item.strip() for item in raw.split(",") if item.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    print("RAG service starting...")
    get_engine()
    yield
    print("RAG service stopped.")


app = FastAPI(
    title="法律辅助咨询 RAG API",
    version="0.2.0",
    description="基于混合检索与 Cookie Session 认证的多用户法律知识库系统。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": app.version,
        "mode": "multi-user",
    }


app.include_router(auth.router, prefix=f"{settings.API_PREFIX}/auth", tags=["auth"])
app.include_router(knowledge_bases.router, prefix=f"{settings.API_PREFIX}/knowledge-bases", tags=["knowledge-bases"])
app.include_router(docs.router, prefix=f"{settings.API_PREFIX}/docs", tags=["docs"])
app.include_router(chat.router, prefix=f"{settings.API_PREFIX}/chat", tags=["chat"])
app.include_router(retrieve.router, prefix=f"{settings.API_PREFIX}/retrieve", tags=["retrieve"])
app.include_router(citations.router, prefix=f"{settings.API_PREFIX}/citations", tags=["citations"])
app.include_router(experiments.router, prefix=f"{settings.API_PREFIX}/experiments", tags=["experiments"])
