from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "法律辅助咨询 RAG 系统"
    DEBUG: bool | str = True
    ENVIRONMENT: str = "development"

    API_PREFIX: str = "/api/v1"
    CORS_ALLOW_ORIGINS: str = "*"
    DATA_DIR: str = "data"
    DATABASE_URL: str = "postgresql://postgres:postgres123@localhost:5432/legal_rag"

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

    EMBEDDING_PROVIDER: str = "siliconflow"
    EMBED_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    VECTOR_DB_BACKEND: str = "chroma"
    CHROMA_PERSIST_DIR: str = "data/chroma"
    CHROMA_COLLECTION_NAME: str = "legal_chunks"

    RERANK_PROVIDER: str = "siliconflow"
    RERANK_MODEL_NAME: str = "BAAI/bge-reranker-base"
    CROSS_ENCODER_DEVICE: str = "cpu"

    # SiliconFlow API
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
