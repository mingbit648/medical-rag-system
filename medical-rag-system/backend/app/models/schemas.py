from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToggleOption(BaseModel):
    enabled: bool = True


class ChunkOption(BaseModel):
    size: int = Field(default=800, ge=100, le=5000)
    overlap: int = Field(default=200, ge=0, le=2000)


class VectorOption(ToggleOption):
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class IndexRequest(BaseModel):
    chunk: ChunkOption = ChunkOption()
    bm25: ToggleOption = ToggleOption()
    vector: VectorOption = VectorOption()


class TopNOption(BaseModel):
    bm25: int = Field(default=50, ge=1, le=200)
    vector: int = Field(default=50, ge=1, le=200)


class FusionOption(BaseModel):
    method: str = "rrf"
    k: int = Field(default=60, ge=1, le=300)


class RerankOption(BaseModel):
    topk: int = Field(default=30, ge=1, le=200)
    topm: int = Field(default=8, ge=1, le=50)


class LLMOption(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    base_url: Optional[str] = None
    api_key: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    query: str = Field(min_length=1)
    topn: TopNOption = TopNOption()
    fusion: FusionOption = FusionOption()
    rerank: RerankOption = RerankOption()
    llm: LLMOption = LLMOption()


class ChatSessionCreateRequest(BaseModel):
    title: Optional[str] = None


class ChatSessionUpdateRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None


class ChatSessionMessageRequest(BaseModel):
    request_id: Optional[str] = None
    query: str = Field(min_length=1)
    topn: TopNOption = TopNOption()
    fusion: FusionOption = FusionOption()
    rerank: RerankOption = RerankOption()
    llm: LLMOption = LLMOption()


class RetrieveDebugRequest(BaseModel):
    query: str = Field(min_length=1)
    topn: TopNOption = TopNOption()
    fusion: FusionOption = FusionOption()
    rerank: RerankOption = RerankOption()


class ExperimentCase(BaseModel):
    query: str = Field(min_length=1)
    relevant_chunk_ids: List[str] = Field(default_factory=list)
    relevant_doc_ids: List[str] = Field(default_factory=list)


class ExperimentRunRequest(BaseModel):
    dataset: List[ExperimentCase] = Field(min_length=1)
    topn: TopNOption = TopNOption()
    fusion: FusionOption = FusionOption()
    rerank: RerankOption = RerankOption()


class ApiEnvelope(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Dict[str, Any]
    trace_id: str
