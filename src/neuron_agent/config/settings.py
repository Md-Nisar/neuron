"""Typed application settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production", "test"]


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    name: str = "neuron-agent"
    version: str = "0.1.0"
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
    enable_langsmith: bool = False
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


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application wiring."""
    return Settings()
