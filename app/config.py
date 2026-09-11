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

    hybrid_vector_weight: float = Field(default=0.72, ge=0.0, le=1.0)
    default_top_k: int = Field(default=8, ge=1, le=50)

    api_host: str = "0.0.0.0"
    api_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
