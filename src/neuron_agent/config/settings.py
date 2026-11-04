# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Typed application settings."""

from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from psycopg.conninfo import conninfo_to_dict
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neuron_agent import __version__
from neuron_agent.errors.base import AuthorizationError, ValidationAppError
from neuron_agent.security.input_policy import validate_safe_url

Environment = Literal["development", "staging", "production", "test"]
CheckpointerBackend = Literal["auto", "memory", "postgres", "none"]
LimitsBackend = Literal["auto", "memory", "postgres"]
AuthMode = Literal["none", "jwt"]
# Knowledge Engine (ADR 0014 K3, K8). `nvidia` is always hosted; `openai_compatible` (TEI, vLLM,
# OpenAI) is whatever the operator declares; `fake` makes no network call.
EmbeddingProviderName = Literal["nvidia", "openai_compatible", "fake"]
ProcessingLocality = Literal["hosted", "self_hosted"]
ProcessingPolicy = Literal["allow_hosted", "self_hosted_only"]
# Browsers send origins as lowercase `scheme://host[:port]`; CORS matching is exact.
# Starlette compares hostnames without the port, so entries can't carry ports or schemes.
# Model identifier prefixes `create_chat_model` can build.
SUPPORTED_PROVIDERS = frozenset({"openai", "nvidia", "anthropic"})
# Instance-metadata names; link-local addresses are refused by address.
_METADATA_HOSTS = frozenset({"metadata.google.internal", "metadata.azure.internal"})
# A host whose last label is numeric is an IPv4 address to URL parsers (WHATWG), in any form.
_NUMERIC_LABEL = re.compile(r"(0x[0-9a-f]*|[0-9]+)")
_HOST_PATTERN = re.compile(r"^(\*|(\*\.)?[a-z0-9.-]+)$")
_ORIGIN_PATTERN = re.compile(r"^https?://([a-z0-9.-]+|\[[0-9a-f:]+\])(:[0-9]{1,5})?$")


_SSLMODE_RANK = {
    "disable": 0,
    "allow": 1,
    "prefer": 2,
    "require": 3,
    "verify-ca": 4,
    "verify-full": 5,
}


def _is_loopback_bind(host: str) -> bool:
    """Whether a bind address is reachable from this machine only."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _is_metadata_host(hostname: str) -> bool:
    """A link-local address, a well-known cloud instance-metadata name, or an IPv4 address in a
    non-canonical form (integer, hex, octal or short), which HTTP clients may read as either."""
    name = hostname.lower().rstrip(".")
    if name in _METADATA_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return bool(_NUMERIC_LABEL.fullmatch(name.rsplit(".", 1)[-1]))
    return address.is_link_local or address == ipaddress.ip_address("fd00:ec2::254")


def _is_internal_host(url: str) -> bool:
    """True unless `validate_safe_url` accepts the URL's literal host as public.

    Names are not resolved and redirects are not followed, so a public name that resolves to a
    private address passes (an accepted gap, see SECURITY.md). The scheme is checked by the
    callers, so `http` is classified like `https` here.
    """
    try:
        validate_safe_url(url, allow_http=True)
    except (AuthorizationError, ValidationAppError):
        return True
    return False


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # A validation error must never echo the raw input: it holds DSNs and keys.
        hide_input_in_errors=True,
    )

    name: str = "neuron-agent"
    version: str = __version__
    env: Environment = "development"
    # Loopback unless set; `neuron-api` refuses a public bind without an explicit APP_ENV.
    host: str = "127.0.0.1"
    # Render sets a bare PORT, which must beat the image's APP_PORT default, so it is first.
    port: int = Field(
        default=8000, ge=1, le=65_535, validation_alias=AliasChoices("PORT", "APP_PORT")
    )
    log_level: str = "INFO"
    default_model: str = "openai:gpt-5.4-mini"
    # Tried in order when the default model's call fails after its retries (ADR 0009). A JSON
    # list such as ["anthropic:<model>", "openai:<model>"]; empty means no fallback.
    fallback_models: list[str] = Field(default_factory=list, max_length=3)
    request_timeout_seconds: int = Field(default=60, ge=1, le=300)
    # MCP servers the operator exposes (ADR 0009): a JSON file, read at start-up.
    mcp_servers: Path | None = None
    # Bearer token per server name, a JSON object. Never the caller's token.
    mcp_bearer_tokens: dict[str, SecretStr] = Field(default_factory=dict)
    mcp_max_output_bytes: int = Field(default=16_384, ge=1024, le=262_144)
    # Per-user memory (ADR 0009): off unless enabled. The limits are per user.
    memory_enabled: bool = False
    memory_max_items: int = Field(default=50, ge=1, le=1000)
    memory_max_chars: int = Field(default=500, ge=20, le=2000)
    memory_ttl_days: int | None = Field(default=None, ge=1, le=3650)
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
    # Production only: names the record (ticket, ADR, review) that approved content capture.
    langsmith_content_approval_record: str | None = Field(default=None, max_length=200)
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
    # Not used by this code: read only so the transport check below sees every header the
    # exporters merge in from the environment themselves.
    otel_exporter_otlp_traces_headers: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "APP_OTEL_EXPORTER_OTLP_TRACES_HEADERS",
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        ),
    )
    otel_exporter_otlp_metrics_headers: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "APP_OTEL_EXPORTER_OTLP_METRICS_HEADERS",
            "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        ),
    )
    # Knowledge Engine (ADR 0014; RAG-01.01). Off until v1.1.0 is released; on, it needs the
    # Postgres checkpointer and a database with the pgvector extension.
    knowledge_enabled: bool = False
    # Knowledge Engine embeddings (ADR 0014 K3, K8; RAG-02.03). The default profile is the spike's
    # (RAG-00.02): NVIDIA's API catalog, for development only, at 1,024 dimensions.
    knowledge_embedding_provider: EmbeddingProviderName = "nvidia"
    knowledge_embedding_model: str = Field(
        default="nvidia/nemotron-3.5-embed-1b", min_length=1, max_length=200
    )
    # pgvector indexes `halfvec` with HNSW up to 4,000 dimensions.
    knowledge_embedding_dimensions: int = Field(default=1024, ge=1, le=4000)
    # Required for `openai_compatible`, the server's `/v1` base URL; `nvidia` ignores it.
    knowledge_embedding_base_url: str | None = None
    # `openai_compatible` only; `nvidia` uses NVIDIA_API_KEY.
    knowledge_embedding_api_key: SecretStr | None = None
    # Where `openai_compatible` processes text. Unset means hosted, which fails closed below.
    knowledge_embedding_locality: ProcessingLocality = "hosted"
    knowledge_embedding_batch_size: int = Field(default=32, ge=1, le=256)
    knowledge_embedding_timeout_seconds: int = Field(default=30, ge=1, le=300)
    knowledge_embedding_max_retries: int = Field(default=3, ge=0, le=8)
    # `self_hosted_only` forbids hosted embedding for every knowledge base.
    knowledge_processing_policy: ProcessingPolicy = "allow_hosted"
    # Original uploaded files (ADR 0014; RAG-01.03). `local` is a directory, normally a volume;
    # staging/production need APP_KNOWLEDGE_BLOB_LOCAL_ALLOWED=true for it (one node, a volume).
    # Parsing caps (RAG-02.02): bytes per file, pages, and extracted characters per page.
    knowledge_parse_max_bytes: int = Field(default=50_000_000, ge=1_024, le=200_000_000)
    knowledge_parse_max_pages: int = Field(default=2_000, ge=1, le=10_000)
    knowledge_parse_max_page_chars: int = Field(default=50_000, ge=1_000, le=200_000)
    # Chunk size in estimated tokens (RAG-02.04): 400 is about the spike's 1,200 characters.
    knowledge_chunk_max_tokens: int = Field(default=400, ge=50, le=8_000)
    # Knowledge bases one user may have (RAG-03.01; ADR 0014 requirement 7). Tombstoned ones
    # do not count.
    knowledge_max_bases_per_user: int = Field(default=20, ge=1, le=1_000)
    # Uploads one API process reads at once (RAG-03.02): each holds up to
    # APP_KNOWLEDGE_PARSE_MAX_BYTES in memory while its type is checked. More are `429`.
    knowledge_upload_concurrency: int = Field(default=4, ge=1, le=64)
    # What one user may hold (RAG-02.05; ADR 0014 requirement 7), checked before an upload is
    # stored. Stored bytes, documents and parsed pages count every document until it is purged;
    # documents being ingested (queued, parsing, embedding) count while their base is live.
    knowledge_max_bytes_per_user: int = Field(default=1_000_000_000, ge=1_024, le=10**13)
    knowledge_max_documents_per_user: int = Field(default=1_000, ge=1, le=100_000)
    knowledge_max_pages_per_user: int = Field(default=20_000, ge=1, le=10_000_000)
    knowledge_max_ingesting_per_user: int = Field(default=5, ge=1, le=1_000)
    # docling-serve for PDF and Office files (RAG-02.02): its base URL, reachable only from the
    # worker; a total deadline per file; and a cap on its JSON reply.
    # No credentials in the URL: docling-serve is reached only over the internal network.
    knowledge_parser_url: str | None = Field(default=None, pattern=r"^https?://[^@/?#]+(/[^@]*)?$")
    knowledge_parser_timeout_seconds: int = Field(default=900, ge=10, le=7_200)
    knowledge_parser_max_response_bytes: int = Field(
        default=64_000_000, ge=1_000_000, le=512_000_000
    )
    knowledge_blob_backend: Literal["local", "s3"] = "local"
    knowledge_blob_root: str = Field(default="var/knowledge-blobs", min_length=1)
    knowledge_blob_local_allowed: bool = False
    # `s3`: a private bucket. The endpoint is for S3-compatible servers; unset means AWS. Unset
    # credentials fall back to the standard AWS chain (environment, web identity, instance role).
    knowledge_blob_bucket: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"
    )
    knowledge_blob_endpoint: str | None = None
    knowledge_blob_region: str | None = None
    knowledge_blob_access_key_id: SecretStr | None = None
    knowledge_blob_secret_access_key: SecretStr | None = None
    # "auto" resolves to memory in development/test; staging/production must choose explicitly.
    checkpointer: CheckpointerBackend = "auto"
    checkpointer_setup_on_startup: bool = False
    # Development/test fake model only (ADR 0012 decision 4); 0 and None keep the instant answer.
    fake_model_ttft_ms: int = Field(default=0, ge=0, le=10_000)
    fake_model_tokens_per_second: int = Field(default=0, ge=0, le=1_000)
    fake_model_output_tokens: int | None = Field(default=None, ge=1, le=2_000)
    # Where the rate limit, token budget and run guards live. "auto" resolves to memory in
    # development/test; staging/production must choose explicitly (production: postgres).
    limits_backend: LimitsBackend = "auto"
    postgres_dsn: SecretStr | None = None
    # Direct, non-pooled DSN of the migrator role; read only by `persistence.cli` (ADR 0008).
    postgres_migration_dsn: SecretStr | None = None
    # The runtime role `setup` grants DML to (ADR 0008 decision 15); a plain role name.
    postgres_app_role: str = Field(default="neuron_app", pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    # The ingestion worker's role (ADR 0014; RAG-01.02): with knowledge on, `setup` grants it the
    # knowledge-table rights it needs, when it exists.
    postgres_worker_role: str = Field(default="neuron_worker", pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    # `neuron-worker` (RAG-02.01): its own DSN, as the worker role; read only by the worker.
    postgres_worker_dsn: SecretStr | None = None
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    # SIGTERM waits this long for running jobs, then releases them to be retried.
    worker_drain_seconds: float = Field(default=30.0, ge=0, le=600)
    # A job whose worker sent no heartbeat for this long is retried by another worker's sweep.
    worker_stalled_seconds: float = Field(default=30.0, ge=3, le=3600)
    # Touched while the worker is healthy; the container health check reads its age. In the
    # user's home, not a world-writable directory.
    worker_health_file: str = Field(
        default_factory=lambda: str(Path.home() / ".neuron-worker.health"), min_length=1
    )
    postgres_pool_max_size: int = Field(default=10, ge=1, le=100)
    postgres_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    max_history_tokens: int = Field(default=8000, ge=256, le=200_000)
    max_thread_messages: int = Field(default=200, ge=2, le=10_000)
    stream_heartbeat_seconds: int = Field(default=15, ge=1, le=120)
    run_timeout_seconds: int = Field(default=120, ge=1, le=900)
    shutdown_drain_seconds: float = Field(default=5.0, ge=0, le=60)
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

    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "APP_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )

    # Only the name LangSmith itself reads: an `APP_`-prefixed copy would pass validation
    # here and still leave the client without a key.
    langsmith_api_key: SecretStr | None = Field(default=None, validation_alias="LANGSMITH_API_KEY")

    @field_validator("postgres_app_role", "postgres_worker_role")
    @classmethod
    def reject_reserved_role_names(cls, value: str) -> str:
        """`pg_` names are reserved for Postgres' predefined roles."""
        if value.startswith("pg_"):
            raise ValueError("postgres role names must not start with pg_")
        return value

    @field_validator(
        "openai_api_key",
        "nvidia_api_key",
        "anthropic_api_key",
        "langsmith_api_key",
        "knowledge_embedding_api_key",
        "knowledge_embedding_base_url",
        "knowledge_parser_url",
        mode="before",
    )
    @classmethod
    def empty_provider_key_is_unset(cls, value: object) -> object:
        """`OPENAI_API_KEY=` (as copied from `.env.example`) means no key, not an empty one."""
        return None if value == "" else value

    @field_validator(
        "knowledge_blob_bucket",
        "knowledge_blob_endpoint",
        "knowledge_blob_region",
        "knowledge_blob_access_key_id",
        "knowledge_blob_secret_access_key",
        mode="before",
    )
    @classmethod
    def blank_blob_setting_is_unset(cls, value: object) -> object:
        """A blank or whitespace-only blob setting means unset, so the checks below see it."""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    def provider_api_key(self, provider: str) -> SecretStr | None:
        """Return the API key for a `default_model` provider prefix, if one is configured."""
        key = {
            "openai": self.openai_api_key,
            "nvidia": self.nvidia_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(provider)
        return key if key is not None and key.get_secret_value() else None

    @model_validator(mode="after")
    def validate_fallback_models(self) -> Settings:
        """Refuse a fallback that could not be built, or that repeats a model."""
        seen = {self.default_model}
        for identifier in self.fallback_models:
            provider, separator, name = identifier.partition(":")
            if provider not in SUPPORTED_PROVIDERS or not separator or not name:
                raise ValueError(
                    "APP_FALLBACK_MODELS entries must be provider:model with provider one of "
                    + ", ".join(sorted(SUPPORTED_PROVIDERS))
                )
            if identifier in seen:
                raise ValueError("APP_FALLBACK_MODELS must not repeat a model")
            seen.add(identifier)
        return self

    @model_validator(mode="after")
    def require_provider_key_outside_tests(self) -> Settings:
        """Fail early for live model execution in production-like environments."""
        if self.env not in {"staging", "production"}:
            return self
        for identifier in (self.default_model, *self.fallback_models):
            provider = identifier.partition(":")[0]
            if provider in SUPPORTED_PROVIDERS and self.provider_api_key(provider) is None:
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
            if self.env in {"staging", "production"}:
                raise ValueError(
                    "APP_CHECKPOINTER=auto is refused in staging/production; "
                    "set postgres, or none for a deliberately stateless deployment"
                )
            self.checkpointer = "memory"
        if self.checkpointer == "memory" and self.env in {"staging", "production"}:
            raise ValueError(
                "APP_CHECKPOINTER=memory is not durable; use postgres or none in staging/production"
            )
        if self.checkpointer == "postgres" and (
            self.postgres_dsn is None or not self.postgres_dsn.get_secret_value()
        ):
            raise ValueError("APP_POSTGRES_DSN is required when APP_CHECKPOINTER=postgres")
        if self.checkpointer_setup_on_startup and self.env in {"staging", "production"}:
            raise ValueError(
                "APP_CHECKPOINTER_SETUP_ON_STARTUP is refused in staging/production; "
                "run `python -m neuron_agent.persistence.cli setup` as a deploy step"
            )
        return self

    @property
    def knowledge_embedding_locality_effective(self) -> ProcessingLocality:
        """Where the configured embedding provider processes document text."""
        if self.knowledge_embedding_provider == "fake":
            return "self_hosted"
        if self.knowledge_embedding_provider == "nvidia":
            return "hosted"
        return self.knowledge_embedding_locality

    @model_validator(mode="after")
    def validate_knowledge_embedding(self) -> Settings:
        """Refuse an embedding setup that cannot work or would send text where policy forbids.

        The endpoint is operator-configured, so it is checked here and not routed through
        `security/egress.py` (ADR 0014 security requirement 4). Errors never echo the URL.
        """
        provider = self.knowledge_embedding_provider
        if self.knowledge_enabled and self.checkpointer != "postgres":
            # Knowledge bases, documents and vectors live only in Postgres.
            raise ValueError("APP_KNOWLEDGE_ENABLED needs APP_CHECKPOINTER=postgres")
        if provider == "nvidia" and "knowledge_embedding_locality" in self.model_fields_set:
            if self.knowledge_embedding_locality != "hosted":
                raise ValueError(
                    "APP_KNOWLEDGE_EMBEDDING_LOCALITY=self_hosted is refused for the nvidia "
                    "provider: NVIDIA's API catalog is hosted"
                )
        if provider == "openai_compatible":
            url = self.knowledge_embedding_base_url
            if url is None:
                raise ValueError(
                    "APP_KNOWLEDGE_EMBEDDING_BASE_URL is required for the openai_compatible "
                    "embedding provider"
                )
            parts = urlsplit(url)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.query
                or parts.fragment
            ):
                raise ValueError(
                    "APP_KNOWLEDGE_EMBEDDING_BASE_URL must be an http(s) URL with a host and "
                    "no credentials, query or fragment"
                )
            if (
                self.env in {"staging", "production"}
                and parts.scheme != "https"
                and self.knowledge_embedding_api_key is not None
            ):
                raise ValueError(
                    "APP_KNOWLEDGE_EMBEDDING_BASE_URL must use https when "
                    "APP_KNOWLEDGE_EMBEDDING_API_KEY is set in staging/production"
                )
        if self.env not in {"staging", "production"}:
            return self
        if provider == "fake":
            raise ValueError(
                "APP_KNOWLEDGE_EMBEDDING_PROVIDER=fake is refused in staging/production"
            )
        if self.knowledge_enabled and provider == "nvidia" and self.nvidia_api_key is None:
            raise ValueError(
                "APP_KNOWLEDGE_ENABLED with the nvidia embedding provider needs NVIDIA_API_KEY "
                "in staging/production"
            )
        if (
            self.knowledge_processing_policy == "self_hosted_only"
            and self.knowledge_embedding_locality_effective == "hosted"
        ):
            raise ValueError(
                "APP_KNOWLEDGE_PROCESSING_POLICY=self_hosted_only forbids the hosted "
                f"{provider} embedding provider in staging/production; configure a "
                "self-hosted openai_compatible provider (APP_KNOWLEDGE_EMBEDDING_LOCALITY="
                "self_hosted)"
            )
        return self

    @model_validator(mode="after")
    def validate_knowledge_blobs(self) -> Settings:
        """Refuse a blob store that is missing what it needs or is not durable where it must be."""
        if self.knowledge_blob_backend == "s3":
            if self.knowledge_blob_bucket is None:
                raise ValueError("APP_KNOWLEDGE_BLOB_BUCKET is required for the s3 blob backend")
            if (self.knowledge_blob_access_key_id is None) != (
                self.knowledge_blob_secret_access_key is None
            ):
                raise ValueError(
                    "APP_KNOWLEDGE_BLOB_ACCESS_KEY_ID and APP_KNOWLEDGE_BLOB_SECRET_ACCESS_KEY "
                    "must be set together"
                )
            if self.knowledge_blob_endpoint is not None:
                parts = urlsplit(self.knowledge_blob_endpoint)
                if (
                    parts.scheme not in {"http", "https"}
                    or not parts.hostname
                    or parts.username is not None
                    or parts.password is not None
                    or parts.query
                    or parts.fragment
                ):
                    raise ValueError(
                        "APP_KNOWLEDGE_BLOB_ENDPOINT must be an http(s) URL with a host and no "
                        "credentials, query or fragment"
                    )
                if self.env in {"staging", "production"} and parts.scheme != "https":
                    raise ValueError(
                        "APP_KNOWLEDGE_BLOB_ENDPOINT must use https in staging/production"
                    )
                if _is_metadata_host(parts.hostname):
                    # Private hosts stay allowed (self-hosted MinIO); instance metadata never.
                    raise ValueError(
                        "APP_KNOWLEDGE_BLOB_ENDPOINT must not be a link-local or cloud metadata "
                        "address"
                    )
        if (
            self.knowledge_enabled
            and self.env in {"staging", "production"}
            and self.knowledge_blob_backend == "local"
            and not self.knowledge_blob_local_allowed
        ):
            raise ValueError(
                "APP_KNOWLEDGE_BLOB_BACKEND=local is refused in staging/production unless "
                "APP_KNOWLEDGE_BLOB_LOCAL_ALLOWED=true (one node with a persistent volume); "
                "use s3"
            )
        if (
            self.knowledge_enabled
            and self.env in {"staging", "production"}
            and self.knowledge_blob_backend == "local"
            and not Path(self.knowledge_blob_root).is_absolute()
        ):
            # A relative root follows the working directory, which is rarely the volume.
            raise ValueError(
                "APP_KNOWLEDGE_BLOB_ROOT must be an absolute path in staging/production"
            )
        return self

    @model_validator(mode="after")
    def validate_fake_model_settings(self) -> Settings:
        """The fake model's latency settings exist for load tests, never for a deployment."""
        if self.env in {"staging", "production"} and (
            self.fake_model_ttft_ms
            or self.fake_model_tokens_per_second
            or self.fake_model_output_tokens is not None
        ):
            raise ValueError("APP_FAKE_MODEL_* settings are refused in staging/production")
        return self

    @model_validator(mode="after")
    def validate_limits_backend(self) -> Settings:
        """Resolve `auto`; a Postgres guard store needs a DSN whatever the checkpointer is."""
        if self.limits_backend == "auto":
            if self.env in {"staging", "production"}:
                raise ValueError(
                    "APP_LIMITS_BACKEND=auto is refused in staging/production; "
                    "set postgres or memory explicitly"
                )
            self.limits_backend = "memory"
        if self.limits_backend == "memory" and self.env == "production":
            raise ValueError(
                "APP_LIMITS_BACKEND=memory is refused in production: per-process guards "
                "are not shared across replicas; use postgres"
            )
        if self.limits_backend == "postgres" and (
            self.postgres_dsn is None or not self.postgres_dsn.get_secret_value()
        ):
            raise ValueError("APP_POSTGRES_DSN is required when APP_LIMITS_BACKEND=postgres")
        if (
            self.limits_backend == "postgres"
            and self.user_token_budget_window_seconds < self.run_timeout_seconds + 15
        ):
            raise ValueError(
                "APP_USER_TOKEN_BUDGET_WINDOW_SECONDS must be at least "
                "APP_RUN_TIMEOUT_SECONDS + 15 when APP_LIMITS_BACKEND=postgres"
            )
        return self

    @model_validator(mode="after")
    def validate_database_roles(self) -> Settings:
        """Production runs the web process and `setup` as different database users.

        Staging may use one role (ADR 0008 decision 17, free plans); production may not. The
        error never carries a DSN or a user name.
        """
        if self.env != "production" or not self.postgres_dsn or not self.postgres_migration_dsn:
            return self
        try:
            users = [
                conninfo_to_dict(dsn.get_secret_value()).get("user")
                for dsn in (self.postgres_dsn, self.postgres_migration_dsn)
            ]
        except Exception:  # noqa: BLE001 - driver messages can echo the DSN
            raise ValueError(
                "APP_POSTGRES_DSN or APP_POSTGRES_MIGRATION_DSN is not valid"
            ) from None
        if users[0] == users[1]:
            raise ValueError(
                "APP_POSTGRES_DSN and APP_POSTGRES_MIGRATION_DSN must use different database "
                "users in production (the runtime user must not own the schema)"
            )
        return self

    @model_validator(mode="after")
    def validate_authentication(self) -> Settings:
        """Require a complete and safe JWT configuration outside local mode."""
        if self.auth_mode == "none":
            if self.env in {"staging", "production"}:
                raise ValueError("APP_AUTH_MODE=none is only allowed in development and test")
            if self.env != "development" and not _is_loopback_bind(self.host):
                raise ValueError(
                    "APP_AUTH_MODE=none must not bind a non-loopback APP_HOST outside "
                    "development; use APP_AUTH_MODE=jwt or APP_HOST=127.0.0.1"
                )
            return self

        if not self.auth_issuer:
            raise ValueError("APP_AUTH_ISSUER is required when APP_AUTH_MODE=jwt")
        if not self.auth_audience:
            raise ValueError("APP_AUTH_AUDIENCE is required when APP_AUTH_MODE=jwt")
        if not self.auth_jwks_url:
            raise ValueError("APP_AUTH_JWKS_URL is required when APP_AUTH_MODE=jwt")
        if self.env != "development" and not self.auth_jwks_url.startswith("https://"):
            raise ValueError("APP_AUTH_JWKS_URL must use HTTPS outside development")
        if self.env in {"staging", "production"} and _is_internal_host(self.auth_jwks_url):
            raise ValueError(
                "APP_AUTH_JWKS_URL must not point at a local, private or otherwise "
                "non-public host in staging/production"
            )
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
    def validate_production_profile(self) -> Settings:
        """Refuse the remaining unsafe staging/production settings (ADR 0008 decision 9).

        Errors name settings, never values: a DSN or an approval record is not echoed.
        """
        if self.env not in {"staging", "production"}:
            return self
        production = self.env == "production"
        if self.memory_enabled and self.checkpointer != "postgres":
            # Memories must outlive a restart, and the tools that write them wait for an approval,
            # which a run can only do where its state is saved (ADR 0009).
            raise ValueError(
                "APP_MEMORY_ENABLED needs APP_CHECKPOINTER=postgres in staging/production"
            )
        if not self.allowed_hosts:
            raise ValueError(
                "APP_ALLOWED_HOSTS must list the served hostnames in staging/production"
            )
        if "trusted_proxies" not in self.model_fields_set:
            raise ValueError(
                "APP_TRUSTED_PROXIES must be set in staging/production "
                "(an explicit [] means no trusted proxy)"
            )
        for proxy in self.trusted_proxies:
            try:
                network = ipaddress.ip_network(proxy.strip(), strict=False)
            except ValueError:
                raise ValueError(
                    "APP_TRUSTED_PROXIES contains an entry that is not an IP address or CIDR range"
                ) from None
            if network.prefixlen < (8 if network.version == 4 else 16):
                raise ValueError(
                    "APP_TRUSTED_PROXIES must not contain a range broader than "
                    "/8 (IPv4) or /16 (IPv6)"
                )
        for host in self.allowed_hosts:
            if host == "*" or (host.startswith("*.") and host.count(".") < 2):
                raise ValueError(
                    "APP_ALLOWED_HOSTS must not contain '*' or a wildcard over a whole "
                    "top-level domain in staging/production"
                )
        if not self.rate_limit_enabled:
            raise ValueError("APP_RATE_LIMIT_ENABLED=false is refused in staging/production")
        # Staging may use `require` (ADR 0008 decision 17, free-plan Render); production may not.
        required_sslmode = "verify-full" if production else "require"
        for name, dsn in (
            ("APP_POSTGRES_DSN", self.postgres_dsn),
            ("APP_POSTGRES_MIGRATION_DSN", self.postgres_migration_dsn),
            ("APP_POSTGRES_WORKER_DSN", self.postgres_worker_dsn),
        ):
            if dsn is not None and dsn.get_secret_value():
                self._require_sslmode(name, dsn, required_sslmode)
        if production and self.expose_api_docs:
            raise ValueError("APP_EXPOSE_API_DOCS=true is refused in production")
        if production and not self.hsts_max_age_seconds:
            raise ValueError(
                "APP_HSTS_MAX_AGE_SECONDS must be greater than 0 in production "
                "(the API is served over TLS only)"
            )
        if (
            production
            and self.langsmith_content_approved
            and not (self.langsmith_content_approval_record or "").strip()
        ):
            raise ValueError(
                "APP_LANGSMITH_CONTENT_APPROVED=true in production needs "
                "APP_LANGSMITH_CONTENT_APPROVAL_RECORD naming the approval record"
            )
        return self

    @staticmethod
    def _require_sslmode(name: str, dsn: SecretStr, minimum: str) -> None:
        try:
            # libpq's default when the DSN says nothing is `prefer`, which allows plaintext.
            sslmode = conninfo_to_dict(dsn.get_secret_value()).get("sslmode") or "prefer"
        except Exception:  # noqa: BLE001 - driver messages can echo the DSN
            raise ValueError(f"{name} is not valid") from None
        if _SSLMODE_RANK.get(str(sslmode), -1) < _SSLMODE_RANK[minimum]:
            raise ValueError(f"{name} must set sslmode={minimum} or stronger in this environment")

    @model_validator(mode="after")
    def validate_telemetry_transport(self) -> Settings:
        """OTLP credentials must not leave the host in clear text outside development/test."""
        endpoint = self.otel_exporter_otlp_endpoint
        headers = (
            self.otel_exporter_otlp_headers,
            self.otel_exporter_otlp_traces_headers,
            self.otel_exporter_otlp_metrics_headers,
        )
        if (
            self.env in {"staging", "production"}
            and any(value is not None and value.get_secret_value() for value in headers)
            and not endpoint.startswith("https://")
            and urlsplit(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError(
                "OTEL_EXPORTER_OTLP_ENDPOINT must use HTTPS when OTEL_EXPORTER_OTLP_HEADERS "
                "(or its _TRACES_/_METRICS_ form) is set in staging/production, unless the "
                "Collector is on loopback"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application wiring."""
    return Settings()
