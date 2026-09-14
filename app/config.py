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
    llm_max_output_tokens: int = Field(default=512, ge=64, le=4096)

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
    web_search_min_hybrid_score: float = Field(default=0.30, ge=0.0, le=1.0)
    web_search_allowed_domains: str = (
        "law.nfa.gov.tw,nfa.gov.tw,law.moj.gov.tw,gazette.nat.gov.tw,"
        "web.law.ntpc.gov.tw,laws.gov.taipei"
    )

    hybrid_vector_weight: float = Field(default=0.72, ge=0.0, le=1.0)
    default_top_k: int = Field(default=8, ge=1, le=50)

    api_host: str = "0.0.0.0"
    api_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
