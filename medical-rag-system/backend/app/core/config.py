from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "法律辅助咨询 RAG 系统"
    DEBUG: bool | str = True
    ENVIRONMENT: str = "development"

    API_PREFIX: str = "/api/v1"
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    DATA_DIR: str = "data"
    UPLOAD_DIR: str = "data/uploads"
    DATABASE_URL: str = "postgresql://postgres:postgres123@localhost:5432/legal_rag"
    DEFAULT_KB_NAME: str = "默认知识库"
    DEFAULT_KB_DESCRIPTION: str = "迁移后的默认共享知识库"
    PRIVATE_DEFAULT_KB_NAME: str = "我的知识库"
    PRIVATE_DEFAULT_KB_DESCRIPTION: str = "用户默认私有知识库"

    AUTH_COOKIE_NAME: str = "legal_rag_session"
    AUTH_SESSION_DAYS: int = 14
    AUTH_COOKIE_SECURE: bool | str = False
    BOOTSTRAP_ADMIN_EMAIL: str = ""
    BOOTSTRAP_ADMIN_PASSWORD: str = ""
    BOOTSTRAP_ADMIN_DISPLAY_NAME: str = "系统管理员"

    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 200
    TOPN_BM25: int = 50
    TOPN_VECTOR: int = 50
    FUSION_K: int = 60
    RERANK_TOPK: int = 30
    RERANK_TOPM: int = 8
    HISTORY_WINDOW_MESSAGES: int = 8
    HISTORY_PROMPT_MESSAGES: int = 6
    ENABLE_HISTORY_FOR_RETRIEVAL: bool = True
    SESSION_CONTEXT_KEEP_RECENT_MESSAGES: int = 6
    SESSION_SUMMARY_TRIGGER_MESSAGES: int = 10
    SESSION_SUMMARY_SOURCE_MESSAGES: int = 80
    SESSION_SUMMARY_MAX_CHARS: int = 1200
    SESSION_SUMMARY_MAX_USER_ITEMS: int = 6
    SESSION_SUMMARY_MAX_ASSISTANT_ITEMS: int = 4
    SESSION_SUMMARY_ITEM_MAX_CHARS: int = 180
    RETRIEVAL_SHORT_QUERY_CHARS: int = 24
    RETRIEVAL_HISTORY_USER_MESSAGES: int = 2
    SESSION_STREAM_STALE_SECONDS: int = 300

    INDEX_JOB_POLL_SECONDS: int = 3
    INDEX_JOB_MAX_ATTEMPTS: int = 3

    EMBEDDING_PROVIDER: str = "hash"
    EMBED_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    VECTOR_DB_BACKEND: str = "chroma"
    CHROMA_PERSIST_DIR: str = "data/chroma"
    CHROMA_COLLECTION_NAME: str = "legal_chunks"

    RERANK_PROVIDER: str = "heuristic"
    RERANK_MODEL_NAME: str = "BAAI/bge-reranker-base"
    CROSS_ENCODER_DEVICE: str = "cpu"

    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    SILICONFLOW_EMBED_MODEL: str = "BAAI/bge-large-zh-v1.5"
    SILICONFLOW_RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"

    LLM_PROVIDER: str = "deepseek"
    DEFAULT_LLM_MODEL: str = "deepseek-chat"
    LLM_TIMEOUT_SECONDS: float = 45.0
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_API_KEY: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
