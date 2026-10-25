"""
Application configuration loaded from environment / .env.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(PROJECT_ROOT / "backend" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "电商商品知识库 RAG 问答系统"
    app_env: str = "dev"
    api_prefix: str = "/api/v1"
    data_dir: Path = Field(default=PROJECT_ROOT / "data")

    jwt_secret: str = "dev-only-change-me-please-32-bytes-min"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    refresh_token_days: int = 7

    admin_username: str = "admin"
    admin_password: str = "123456"
    seed_demo_user: bool = True

    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_native_url: str = "https://dashscope.aliyuncs.com/api/v1"
    chat_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    rerank_model: str = "gte-rerank-v2"
    ocr_model: str = "qwen-vl-ocr"
    llm_mode: str = "auto"  # auto | dashscope | mock
    embedding_batch_size: int = 10
    llm_timeout_seconds: float = 90.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_chat_per_min: int = 20
    rate_limit_login_per_min: int = 15
    rate_limit_register_per_min: int = 10
    rate_limit_api_per_min: int = 240
    max_upload_mb: int = 50
    upload_max_files: int = 10

    cache_enabled: bool = True
    cache_ttl_seconds: int = 86400
    cache_fuzzy_threshold: float = 0.95
    retrieval_top_k_dense: int = 40
    retrieval_top_k_sparse: int = 40
    retrieval_fuse_k: int = 30
    rerank_top_n: int = 8
    context_char_budget: int = 6000
    parent_chunk_size: int = 1200
    child_chunk_size: int = 300
    parent_chunk_overlap: int = 100
    child_chunk_overlap: int = 50
    ingest_max_attempts: int = 3
    ingest_workers: int = 4

    @field_validator("data_dir", mode="after")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()

    @property
    def use_dashscope(self) -> bool:
        if self.llm_mode == "mock":
            return False
        if self.llm_mode == "dashscope":
            return bool(self.dashscope_api_key)
        return bool(self.dashscope_api_key)

    @property
    def effective_llm_mode(self) -> str:
        return "dashscope" if self.use_dashscope else "mock"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
