from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Smart CS Agent"
    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = True
    api_v1_prefix: str = "/api/v1"

    jwt_secret_key: SecretStr = SecretStr("change-me-in-production")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    cookie_secure: bool = False
    cookie_domain: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = "sqlite+aiosqlite:///./data/smart_cs.db"
    auto_create_tables: bool = True
    auto_seed: bool = False

    checkpoint_backend: Literal["memory", "postgres"] = "memory"
    checkpoint_database_url: str = "postgresql://smart_cs:smart_cs@localhost:5432/smart_checkpoints"

    redis_url: str = "redis://localhost:6379/0"
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    chroma_host: str | None = None
    chroma_port: int = 8000
    chroma_collection: str = "after_sales_policies"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_enabled: bool = True
    model_cache_dir: Path = PROJECT_ROOT / "data" / "models"
    rag_top_k: int = 12
    rag_final_k: int = 4
    rag_chunk_size: int = 600
    rag_chunk_overlap: int = 100

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY"),
    )
    llm_temperature: float = 0.0

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "http://localhost:3001"

    notification_provider: Literal["mock", "dingtalk"] = "mock"
    dingtalk_webhook: SecretStr | None = None

    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    max_upload_mb: int = 20

    @field_validator("model_cache_dir", "upload_dir", mode="after")
    @classmethod
    def ensure_directory(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_api_key_value(self) -> str | None:
        if self.llm_api_key is None:
            return None
        value = self.llm_api_key.get_secret_value().strip()
        return value or None

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
