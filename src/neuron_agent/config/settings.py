# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Typed application settings."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neuron_agent import __version__

Environment = Literal["development", "staging", "production", "test"]
CheckpointerBackend = Literal["auto", "memory", "postgres", "none"]
AuthMode = Literal["none", "jwt"]
# Browsers send origins as lowercase `scheme://host[:port]`; CORS matching is exact.
# Starlette compares hostnames without the port, so entries can't carry ports or schemes.
_HOST_PATTERN = re.compile(r"^(\*|(\*\.)?[a-z0-9.-]+)$")
_ORIGIN_PATTERN = re.compile(r"^https?://([a-z0-9.-]+|\[[0-9a-f:]+\])(:[0-9]{1,5})?$")


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    name: str = "neuron-agent"
    version: str = __version__
    env: Environment = "development"
    log_level: str = "INFO"
    default_model: str = "openai:gpt-5.4-mini"
    request_timeout_seconds: int = Field(default=60, ge=1, le=300)
    tool_timeout_seconds: int = Field(default=20, ge=1, le=60)
    max_agent_iterations: int = Field(default=8, ge=1, le=25)
    provider_max_retries: int = Field(default=2, ge=0, le=5)
    max_output_tokens: int = Field(default=2000, ge=1, le=16_384)
    max_prompt_chars: int = Field(default=12_000, ge=100, le=200_000)
    max_request_body_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_window: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_burst: int = Field(default=20, ge=1, le=10_000)
    trusted_proxies: list[str] = Field(default_factory=list)
    enable_langsmith: bool = False
    # Outside development, LangSmith traces carry no prompts or answers unless this is true.
    langsmith_content_approved: bool = False
    otel_enabled: bool = False
    # None uses APP_NAME.
    otel_service_name: str | None = None
    # Head sampling for new traces; an incoming `traceparent` keeps its sampled flag.
    otel_traces_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_export_timeout_seconds: float = Field(default=10.0, gt=0.0, le=60.0)
    # Read under the standard OpenTelemetry names; the exporter appends /v1/traces etc.
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4318",
        pattern=r"^https?://",
        validation_alias=AliasChoices(
            "APP_OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
        ),
    )
    # `key=value` pairs, comma-separated and URL-encoded, such as an auth header.
    otel_exporter_otlp_headers: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "APP_OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_HEADERS",
        ),
    )
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
    max_concurrent_runs_per_user: int = Field(default=2, ge=1, le=1000)
    user_token_budget: int = Field(default=100_000, ge=1, le=10_000_000)
    user_token_budget_window_seconds: int = Field(default=3600, ge=1, le=86_400)
    thread_retention_days: int = Field(default=30, ge=1, le=3650)
    user_data_export_max_bytes: int = Field(default=5_000_000, ge=65_536, le=50_000_000)
    auth_mode: AuthMode = "none"
    auth_issuer: str | None = None
    auth_issuer_id: str = Field(
        default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    )
    auth_audit_success_enabled: bool = False
    auth_audience: str | None = None
    auth_jwks_url: str | None = None
    auth_algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])
    auth_leeway_seconds: int = Field(default=30, ge=0, le=300)
    auth_jwks_cache_seconds: int = Field(default=300, ge=1, le=86_400)
    auth_jwks_timeout_seconds: int = Field(default=5, ge=1, le=30)
    auth_token_max_bytes: int = Field(default=16_384, ge=1024, le=131_072)
    auth_require_typ: bool = False
    auth_scope_claim: str = "scope"
    auth_roles_claim: str | None = "roles"
    auth_role_permissions: dict[str, list[str]] = Field(default_factory=dict)
    identity_hash_key: SecretStr | None = None
    cors_allowed_origins: list[str] = Field(default_factory=list)
    # None resolves to exposed in development/test and hidden in staging/production.
    expose_api_docs: bool | None = None
    # Empty disables the Host check; `/health/*` is always exempt for platform probes.
    allowed_hosts: list[str] = Field(default_factory=list)
    # 0 disables HSTS; set it only when every client reaches the API over TLS.
    hsts_max_age_seconds: int = Field(default=0, ge=0, le=63_072_000)
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "APP_OPENAI_API_KEY",
            "OPENAI_API_KEY",
        ),
    )

    nvidia_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "APP_NVIDIA_API_KEY",
            "NVIDIA_API_KEY",
        ),
    )

    # Only the name LangSmith itself reads: an `APP_`-prefixed copy would pass validation
    # here and still leave the client without a key.
    langsmith_api_key: SecretStr | None = Field(default=None, validation_alias="LANGSMITH_API_KEY")

    @field_validator("openai_api_key", "nvidia_api_key", "langsmith_api_key", mode="before")
    @classmethod
    def empty_provider_key_is_unset(cls, value: object) -> object:
        """`OPENAI_API_KEY=` (as copied from `.env.example`) means no key, not an empty one."""
        return None if value == "" else value

    def provider_api_key(self, provider: str) -> SecretStr | None:
        """Return the API key for a `default_model` provider prefix, if one is configured."""
        key = {"openai": self.openai_api_key, "nvidia": self.nvidia_api_key}.get(provider)
        return key if key is not None and key.get_secret_value() else None

    @model_validator(mode="after")
    def require_provider_key_outside_tests(self) -> Settings:
        """Fail early for live model execution in production-like environments."""
        provider = self.default_model.partition(":")[0]
        if (
            self.env in {"staging", "production"}
            and provider in {"openai", "nvidia"}
            and self.provider_api_key(provider) is None
        ):
            raise ValueError(
                f"{provider.upper()}_API_KEY is required for {provider} models "
                "in staging/production"
            )
        return self

    @model_validator(mode="after")
    def require_langsmith_key_when_enabled(self) -> Settings:
        """Fail early rather than silently dropping traces in production-like environments."""
        if (
            self.enable_langsmith
            and self.env in {"staging", "production"}
            and (self.langsmith_api_key is None or not self.langsmith_api_key.get_secret_value())
        ):
            raise ValueError(
                "LANGSMITH_API_KEY is required when APP_ENABLE_LANGSMITH=true in staging/production"
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

    @model_validator(mode="after")
    def validate_authentication(self) -> Settings:
        """Require a complete and safe JWT configuration outside local mode."""
        if self.auth_mode == "none":
            if self.env in {"staging", "production"}:
                raise ValueError("APP_AUTH_MODE=none is only allowed in development and test")
            return self

        if not self.auth_issuer:
            raise ValueError("APP_AUTH_ISSUER is required when APP_AUTH_MODE=jwt")
        if not self.auth_audience:
            raise ValueError("APP_AUTH_AUDIENCE is required when APP_AUTH_MODE=jwt")
        if not self.auth_jwks_url:
            raise ValueError("APP_AUTH_JWKS_URL is required when APP_AUTH_MODE=jwt")
        if self.env != "development" and not self.auth_jwks_url.startswith("https://"):
            raise ValueError("APP_AUTH_JWKS_URL must use HTTPS outside development")
        if not self.auth_algorithms or any(
            algorithm not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
            for algorithm in self.auth_algorithms
        ):
            raise ValueError("APP_AUTH_ALGORITHMS must contain only allowed asymmetric algorithms")
        if self.identity_hash_key is None or len(self.identity_hash_key.get_secret_value()) < 32:
            raise ValueError("APP_IDENTITY_HASH_KEY must be at least 32 characters in JWT mode")
        return self

    @model_validator(mode="after")
    def validate_http_surface(self) -> Settings:
        """Resolve the docs default and reject origins and hosts that can't be safe or match."""
        if self.expose_api_docs is None:
            self.expose_api_docs = self.env in {"development", "test"}
        for origin in self.cors_allowed_origins:
            if origin == "*":
                raise ValueError(
                    "APP_CORS_ALLOWED_ORIGINS must not contain '*': requests carry credentials "
                    "in the Authorization header, so list each trusted origin explicitly"
                )
            if not _ORIGIN_PATTERN.fullmatch(origin):
                raise ValueError(
                    f"APP_CORS_ALLOWED_ORIGINS entry {origin!r} must be a lowercase "
                    "scheme://host[:port] origin with no path or trailing slash"
                )
        for host in self.allowed_hosts:
            if not _HOST_PATTERN.fullmatch(host):
                raise ValueError(
                    f"APP_ALLOWED_HOSTS entry {host!r} must be a lowercase hostname with no "
                    "scheme or port, optionally starting with '*.'"
                )
        return self

    @model_validator(mode="after")
    def validate_telemetry_transport(self) -> Settings:
        """OTLP credentials must not leave the host in clear text outside development/test."""
        endpoint = self.otel_exporter_otlp_endpoint
        if (
            self.env in {"staging", "production"}
            and self.otel_exporter_otlp_headers is not None
            and self.otel_exporter_otlp_headers.get_secret_value()
            and not endpoint.startswith("https://")
            and urlsplit(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError(
                "OTEL_EXPORTER_OTLP_ENDPOINT must use HTTPS when OTEL_EXPORTER_OTLP_HEADERS "
                "is set in staging/production, unless the Collector is on loopback"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application wiring."""
    return Settings()
