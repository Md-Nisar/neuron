"""Typed application settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production", "test"]
CheckpointerBackend = Literal["auto", "memory", "postgres", "none"]


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    name: str = "neuron-agent"
    version: str = "0.2.0"
    env: Environment = "development"
    log_level: str = "INFO"
    default_model: str = "openai:gpt-5.4-mini"
    request_timeout_seconds: int = Field(default=60, ge=1, le=300)
    tool_timeout_seconds: int = Field(default=20, ge=1, le=60)
    max_agent_iterations: int = Field(default=5, ge=1, le=25)
    provider_max_retries: int = Field(default=2, ge=0, le=5)
    max_output_tokens: int = Field(default=2000, ge=1, le=16_384)
    max_prompt_chars: int = Field(default=12_000, ge=100, le=200_000)
    max_request_body_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_window: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_burst: int = Field(default=20, ge=1, le=10_000)
    enable_langsmith: bool = False
    # "auto" resolves to memory in development/test and none in staging/production.
    checkpointer: CheckpointerBackend = "auto"
    checkpointer_setup_on_startup: bool = False
    postgres_dsn: SecretStr | None = None
    postgres_pool_max_size: int = Field(default=10, ge=1, le=100)
    postgres_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    max_history_tokens: int = Field(default=8000, ge=256, le=200_000)
    max_thread_messages: int = Field(default=200, ge=2, le=10_000)
    stream_heartbeat_seconds: int = Field(default=15, ge=1, le=120)
    run_timeout_seconds: int = Field(default=120, ge=1, le=900)
    max_concurrent_streams: int = Field(default=100, ge=1, le=10_000)
    thread_retention_days: int = Field(default=30, ge=1, le=3650)
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "APP_OPENAI_API_KEY",
            "OPENAI_API_KEY",
        ),
    )

    @model_validator(mode="after")
    def require_provider_key_outside_tests(self) -> Settings:
        """Fail early for live model execution in production-like environments."""
        if self.env in {"staging", "production"} and self.default_model.startswith("openai:"):
            if self.openai_api_key is None or not self.openai_api_key.get_secret_value():
                raise ValueError(
                    "OPENAI_API_KEY is required for OpenAI models in staging/production"
                )
        return self

    @model_validator(mode="after")
    def validate_checkpointer(self) -> Settings:
        """Resolve `auto` and reject backends that cannot work in the configured environment."""
        if self.checkpointer == "auto":
            self.checkpointer = "memory" if self.env in {"development", "test"} else "none"
        if self.checkpointer == "memory" and self.env in {"staging", "production"}:
            raise ValueError(
                "APP_CHECKPOINTER=memory is not durable; use postgres or none in staging/production"
            )
        if self.checkpointer == "postgres" and (
            self.postgres_dsn is None or not self.postgres_dsn.get_secret_value()
        ):
            raise ValueError("APP_POSTGRES_DSN is required when APP_CHECKPOINTER=postgres")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application wiring."""
    return Settings()
