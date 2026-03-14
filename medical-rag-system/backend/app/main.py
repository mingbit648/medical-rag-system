from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.rag_engine import get_engine
from app.routers import chat, citations, docs, experiments, retrieve


@asynccontextmanager
async def lifespan(_: FastAPI):
    print("RAG service starting...")
    get_engine()
    yield
    print("RAG service stopped.")


app = FastAPI(
    title="法律辅助咨询 RAG API",
    version="0.1.0",
    description="基于混合检索 + 重排序的最小可运行工程壳。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.CORS_ALLOW_ORIGINS == "*" else settings.CORS_ALLOW_ORIGINS.split(","),
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
        "mode": "minimal-shell",
    }


app.include_router(docs.router, prefix=f"{settings.API_PREFIX}/docs", tags=["docs"])
app.include_router(chat.router, prefix=f"{settings.API_PREFIX}/chat", tags=["chat"])
app.include_router(retrieve.router, prefix=f"{settings.API_PREFIX}/retrieve", tags=["retrieve"])
app.include_router(citations.router, prefix=f"{settings.API_PREFIX}/citations", tags=["citations"])
app.include_router(experiments.router, prefix=f"{settings.API_PREFIX}/experiments", tags=["experiments"])
