from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    nfa_category_url: str = "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002"
    nfa_allowed_host: str = "law.nfa.gov.tw"
    crawl_delay_seconds: float = 2.0
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3
    max_attachment_bytes: int = Field(default=25_000_000, ge=1_000_000, le=200_000_000)
    max_attachment_pages: int = Field(default=200, ge=1, le=5000)
    user_agent: str = "NFA-Fire-Law-RAG/0.1 (+personal research; respectful crawler)"
    category_link_selector: str = ""
    detail_content_selector: str = ""
    nfa_prefer_print_view: bool = True

    # SQLite is the zero-setup default. Use STORAGE_BACKEND=postgres for the
    # optional PostgreSQL/pgvector deployment.
    storage_backend: str = "sqlite"
    database_url: str = "sqlite:///./data/nfa_fire_law.db"
    sqlite_fts_candidate_limit: int = Field(default=300, ge=20, le=5000)

    embedding_provider: str = "hash"
    embedding_dim: int = 384
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    # Ollama answer generation is optional at runtime but enabled by default for
    # the supported Gemma 4 cloud/local setup. Retrieval remains independent.
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_cloud_base_url: str = "https://ollama.com"
    llm_model: str = "gemma4:31b-cloud"
    llm_timeout_seconds: float = Field(default=180.0, ge=1.0, le=900.0)
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_think: bool = False
    # Unknown/custom models use this conservative fallback. Supported frontend
    # models have explicit context/output profiles below.
    llm_max_output_tokens: int = Field(default=1024, ge=64, le=32768)
    llm_e2b_context_tokens: int = Field(default=8192, ge=4096, le=131072)
    llm_e2b_max_output_tokens: int = Field(default=2048, ge=64, le=32768)
    llm_e4b_context_tokens: int = Field(default=16384, ge=4096, le=131072)
    llm_e4b_max_output_tokens: int = Field(default=4096, ge=64, le=32768)
    llm_31b_cloud_context_tokens: int = Field(default=262144, ge=4096, le=1048576)
    llm_31b_cloud_max_output_tokens: int = Field(default=8192, ge=64, le=65536)
    llm_unknown_context_tokens: int = Field(default=4096, ge=1024, le=1048576)
    llm_context_safety_tokens: int = Field(default=512, ge=64, le=8192)
    llm_capability_discovery_enabled: bool = True
    llm_capability_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    llm_completion_retry_limit: int = Field(default=1, ge=0, le=2)

    # Web search is a bounded, optional fallback. It requires an Ollama hosted
    # web-search API key; local Gemma remains the answer generator.
    web_search_enabled: bool = True
    web_search_provider: str = "ollama"
    ollama_api_key: str = ""
    web_search_api_url: str = "https://ollama.com/api/web_search"
    web_fetch_api_url: str = "https://ollama.com/api/web_fetch"
    web_search_timeout_seconds: float = Field(default=30.0, ge=1.0, le=180.0)
    web_search_max_results: int = Field(default=5, ge=1, le=10)
    web_search_max_fetch_results: int = Field(default=3, ge=1, le=5)
    web_search_min_hybrid_score: float = Field(default=0.35, ge=0.0, le=1.0)
    web_search_allowed_domains: str = (
        "law.nfa.gov.tw,nfa.gov.tw,law.moj.gov.tw,gazette.nat.gov.tw,"
        "web.law.ntpc.gov.tw,laws.gov.taipei"
    )

    # The deterministic hash embedder is useful offline, but its cosine score is
    # not semantic enough to dominate legal-term matching. Trained embedding
    # providers keep the original vector-heavy blend.
    hash_vector_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    hybrid_vector_weight: float = Field(default=0.72, ge=0.0, le=1.0)
    law_title_match_boost: float = Field(default=0.12, ge=0.0, le=1.0)
    default_top_k: int = Field(default=8, ge=1, le=50)

    # Answer-facing retrieval can use Gemma cloud to rerank ambiguous
    # role comparison/scope questions. Raw search remains deterministic.
    reranker_enabled: bool = True
    reranker_provider: str = "ollama"
    reranker_model: str = "gemma4:31b-cloud"
    reranker_candidate_limit: int = Field(default=24, ge=8, le=50)
    reranker_input_limit: int = Field(default=12, ge=8, le=24)
    reranker_timeout_seconds: float = Field(default=30.0, ge=1.0, le=180.0)
    reranker_max_output_tokens: int = Field(default=128, ge=32, le=1024)
    reranker_max_chars_per_candidate: int = Field(default=160, ge=80, le=2000)

    api_host: str = "0.0.0.0"
    api_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
