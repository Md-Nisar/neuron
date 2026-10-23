from __future__ import annotations

import io
import json
import os
import re
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import jwt.api_jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

# Must run before importing neuron_agent: settings and the exported graph build at import.
os.environ.setdefault("APP_ENV", "test")
# Developer shells and `.env` may hold provider credentials. Unit tests must never turn
# those into live LLM calls, so the model is pinned and every key is blanked: an empty
# environment variable overrides `.env` and means "no key". Only the live suites get the
# real values back, through the `live_provider` fixture.
_LIVE_VARS = (
    "APP_DEFAULT_MODEL",
    "APP_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "APP_NVIDIA_API_KEY",
    "NVIDIA_API_KEY",
)
_dotenv = dotenv_values(".env") if os.path.isfile(".env") else {}
_LIVE_ENV = {n: v for n in _LIVE_VARS if (v := os.environ.get(n) or _dotenv.get(n))}
os.environ["APP_DEFAULT_MODEL"] = "openai:gpt-5.4-mini"
# A developer `.env` may enable OpenTelemetry; tests must not export to a real Collector.
os.environ["APP_OTEL_ENABLED"] = "false"
# Likewise a developer `.env` or shell must not turn on LangSmith tracing in tests.
os.environ["APP_ENABLE_LANGSMITH"] = "false"
for _name in _LIVE_VARS[1:]:
    os.environ[_name] = ""

from neuron_agent.api import main as api_main  # noqa: E402
from neuron_agent.config.settings import Settings, get_settings  # noqa: E402
from neuron_agent.graphs import main_graph  # noqa: E402
from neuron_agent.models import factory  # noqa: E402
from neuron_agent.schemas.agent import AgentAnswer  # noqa: E402
from neuron_agent.security.auth import TokenVerifier  # noqa: E402
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter  # noqa: E402
from neuron_agent.services.agent_service import AgentService  # noqa: E402


@pytest.fixture
def live_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Restore the developer's model and provider key for a live test; skip without a key.

    The model comes from `APP_DEFAULT_MODEL` in the shell or `.env` (default OpenAI), and
    `Settings()` and `get_settings()` see it and its key for the rest of the test.
    """
    model = _LIVE_ENV.get("APP_DEFAULT_MODEL", "openai:gpt-5.4-mini")
    key_name = f"{model.partition(':')[0].upper()}_API_KEY"
    if not (_LIVE_ENV.get(key_name) or _LIVE_ENV.get(f"APP_{key_name}")):
        pytest.skip(f"{key_name} is not configured for {model}")
    for name in _LIVE_VARS:
        # A blanked `APP_` alias would otherwise shadow a key set under its conventional name.
        if name in _LIVE_ENV:
            monkeypatch.setenv(name, _LIVE_ENV[name])
        else:
            monkeypatch.delenv(name)
    get_settings.cache_clear()
    yield model
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own API rate limiter so request counts don't leak across tests."""
    settings = api_main.settings
    for name in ("ip_rate_limiter", "principal_rate_limiter"):
        monkeypatch.setattr(
            api_main,
            name,
            InMemoryTokenBucketRateLimiter(
                capacity=settings.rate_limit_burst,
                requests_per_window=settings.rate_limit_requests_per_window,
                window_seconds=settings.rate_limit_window_seconds,
            ),
        )


class HistoryEchoAgent:
    """Deterministic agent: answers with every user turn it was given, oldest first.

    It also returns an intermediate tool-call/tool-result pair, the way `create_agent` does,
    so tests can assert that those internal messages are not persisted to the thread. The
    call is a refused one, so `used_tools` stays empty for callers without the tool's scope.
    """

    def __init__(self) -> None:
        self.calls: list[list[BaseMessage]] = []
        self.fail_next = False

    async def ainvoke(
        self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        messages = list(inputs["messages"])
        self.calls.append(messages)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("agent failed")
        answer = " | ".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        tool_call = {"name": "calculator", "args": {"expression": "1+1"}, "id": "call-1"}
        return {
            "messages": [
                *messages,
                AIMessage(content="", tool_calls=[tool_call]),
                ToolMessage(
                    content="tool is not authorized", tool_call_id="call-1", status="error"
                ),
                AIMessage(content=answer),
            ],
            "structured_response": AgentAnswer(answer=answer, used_tools=[], confidence=1.0),
        }


@pytest.fixture
def echo_agent(monkeypatch: pytest.MonkeyPatch) -> HistoryEchoAgent:
    """Make every graph built during the test use a `HistoryEchoAgent`."""
    agent = HistoryEchoAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    return agent


class StreamingFakeModel(GenericFakeChatModel):
    """Streams scripted replies chunk by chunk; tool binding is a no-op.

    Unlike the base class, tool calls are streamed too: as `tool_call_chunks` whose JSON
    arguments arrive in small fragments, the way OpenAI streams them.
    """

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = next(self.messages)
        if not isinstance(reply, AIMessage) or not reply.tool_calls:
            yield from _content_chunks(reply, run_manager)
            return
        message_id = f"run-{uuid.uuid4()}"
        for index, call in enumerate(reply.tool_calls):
            args = json.dumps(call["args"])
            pieces = [args[i : i + 4] for i in range(0, len(args), 4)]
            for n, piece in enumerate(pieces):
                tool_chunk = tool_call_chunk(
                    name=call["name"] if n == 0 else None,
                    args=piece,
                    id=call["id"] if n == 0 else None,
                    index=index,
                )
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(content="", id=message_id, tool_call_chunks=[tool_chunk])
                )
                if run_manager:
                    run_manager.on_llm_new_token("", chunk=chunk)
                yield chunk

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self


def _content_chunks(
    reply: BaseMessage, run_manager: CallbackManagerForLLMRun | None
) -> Iterator[ChatGenerationChunk]:
    message_id = f"run-{uuid.uuid4()}"
    for token in re.split(r"(\s)", str(reply.content)):
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=token, id=message_id))
        if run_manager:
            run_manager.on_llm_new_token(token, chunk=chunk)
        yield chunk


@pytest.fixture
def stream_replies(monkeypatch: pytest.MonkeyPatch) -> Callable[..., StreamingFakeModel]:
    """Make the chat model a `StreamingFakeModel` that replies with the given messages."""

    def use(*replies: AIMessage) -> StreamingFakeModel:
        model = StreamingFakeModel(messages=iter(replies))
        monkeypatch.setattr(factory, "create_chat_model", lambda settings: model)
        return model

    return use


# --- JWT authentication fixtures (v0.4.0) ------------------------------------------
#
# A local key pair per algorithm, a JWKS served in process, and a token factory. The real
# `TokenVerifier` and `PyJWKClient` run unchanged: only the HTTP fetch of the configured
# JWKS URL is replaced, so no test makes a network call.

JWT_ISSUER = "https://issuer.example.test"
JWT_AUDIENCE = "neuron-api"
JWKS_URL = "https://issuer.example.test/.well-known/jwks.json"
ALL_SCOPES = "agent:invoke threads:read threads:delete tools:calculator"


@dataclass(frozen=True)
class JwtKeys:
    """Signing keys trusted by the in-process JWKS, keyed by `kid`."""

    rsa: rsa.RSAPrivateKey
    ec: ec.EllipticCurvePrivateKey
    rsa_kid: str = "rsa-1"
    ec_kid: str = "ec-1"


@pytest.fixture(scope="session")
def jwt_keys() -> JwtKeys:
    return JwtKeys(
        rsa=rsa.generate_private_key(public_exponent=65_537, key_size=2048),
        ec=ec.generate_private_key(ec.SECP256R1()),
    )


@dataclass
class JwksServer:
    """The identity provider's JWKS endpoint, served in process."""

    keys: list[dict[str, Any]]
    requested_urls: list[str] = field(default_factory=list)


@pytest.fixture
def jwks_server(monkeypatch: pytest.MonkeyPatch, jwt_keys: JwtKeys) -> JwksServer:
    """Serve the trusted public keys at `JWKS_URL`; refuse every other URL."""
    server = JwksServer(
        keys=[
            _public_jwk(jwt_keys.rsa, jwt_keys.rsa_kid, "RS256"),
            _public_jwk(jwt_keys.ec, jwt_keys.ec_kid, "ES256"),
        ]
    )

    class Opener:
        def open(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
            url = request.full_url
            server.requested_urls.append(url)
            if url != JWKS_URL:
                raise AssertionError(f"unexpected JWKS fetch: {url}")
            return io.BytesIO(json.dumps({"keys": server.keys}).encode())

    # PyJWKClient.fetch_data opens the JWKS URL through `urllib.request.build_opener`. If a
    # PyJWT upgrade changes that, the AssertionError above or a real fetch attempt shows it.
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    return server


def _public_jwk(private: Any, kid: str, alg: str) -> dict[str, Any]:
    algorithm = jwt.get_algorithm_by_name(alg)
    jwk = json.loads(algorithm.to_jwk(private.public_key()))
    return {**jwk, "kid": kid, "alg": alg, "use": "sig"}


@pytest.fixture
def make_token(jwt_keys: JwtKeys) -> Callable[..., str]:
    """Mint an access token; every argument can be overridden to build an attack.

    `exp` and `nbf` are offsets from now. A claim set to `None` is left out. `key` and
    `kid` default to the trusted key for `alg`.
    """

    def make(
        sub: str | None = "alice",
        *,
        iss: str | None = JWT_ISSUER,
        aud: str | None = JWT_AUDIENCE,
        scopes: str | None = ALL_SCOPES,
        exp: timedelta = timedelta(minutes=5),
        nbf: timedelta = timedelta(0),
        alg: str = "RS256",
        kid: str | None = None,
        key: Any = None,
        headers: dict[str, Any] | None = None,
        **claims: Any,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "iss": iss,
            "aud": aud,
            "sub": sub,
            "scope": scopes,
            "iat": int(now.timestamp()),
            "nbf": int((now + nbf).timestamp()),
            "exp": int((now + exp).timestamp()),
            "jti": str(uuid.uuid4()),
            **claims,
        }
        if key is None:
            key = jwt_keys.ec if alg.startswith("ES") else jwt_keys.rsa
        if kid is None:
            kid = jwt_keys.ec_kid if alg.startswith("ES") else jwt_keys.rsa_kid
        return jwt.encode(
            {name: value for name, value in payload.items() if value is not None},
            key,
            algorithm=alg,
            headers={"kid": kid, **(headers or {})},
        )

    return make


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


#: The explicit choices staging and production require (ADR 0008 decision 9).
PRODUCTION_PROFILE: dict[str, Any] = {
    "checkpointer": "none",
    "limits_backend": "postgres",
    "postgres_dsn": "postgresql://app@db.example.test/neuron?sslmode=verify-full",
    "allowed_hosts": ["api.example.test", "testserver"],
    "trusted_proxies": [],
    "hsts_max_age_seconds": 31_536_000,
}


def jwt_settings(**overrides: Any) -> Settings:
    """Production-shaped JWT settings for the test issuer, with request rate limits off.

    In staging/production the rate limit stays on and `PRODUCTION_PROFILE` fills in the
    settings those environments require; `overrides` still win.
    """
    hardened = overrides.get("env") in {"staging", "production"}
    return Settings(
        **{
            "env": "test",
            "auth_mode": "jwt",
            "auth_issuer": JWT_ISSUER,
            "auth_audience": JWT_AUDIENCE,
            "auth_jwks_url": JWKS_URL,
            "identity_hash_key": "h" * 32,
            "rate_limit_enabled": hardened,
            **(PRODUCTION_PROFILE if hardened else {}),
            **overrides,
        }
    )


@dataclass
class JwtApi:
    """A FastAPI test client wired to a real verifier and a fresh in-memory service."""

    client: TestClient
    settings: Settings
    service: AgentService
    jwks: JwksServer


@pytest.fixture
def jwt_api_factory(
    monkeypatch: pytest.MonkeyPatch, jwks_server: JwksServer
) -> Iterator[Callable[..., JwtApi]]:
    """Build the API in JWT mode; keyword arguments override `jwt_settings`."""
    clients: list[TestClient] = []

    def build(**overrides: Any) -> JwtApi:
        settings = jwt_settings(**overrides)
        if settings.env in {"staging", "production"}:
            # Validation accepted the production profile; the in-process service has no database.
            settings = settings.model_copy(update={"limits_backend": "memory"})
        service = AgentService(settings)
        monkeypatch.setattr(api_main, "settings", settings)
        monkeypatch.setattr(api_main, "service", service)
        monkeypatch.setattr(api_main, "auth_verifier", TokenVerifier(settings))
        client = TestClient(api_main.app)
        client.__enter__()
        clients.append(client)
        return JwtApi(client=client, settings=settings, service=service, jwks=jwks_server)

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def jwt_api(jwt_api_factory: Callable[..., JwtApi], echo_agent: HistoryEchoAgent) -> JwtApi:
    """The API in JWT mode, answering with the deterministic `HistoryEchoAgent`."""
    return jwt_api_factory()


class JwtClock(datetime):
    """The clock PyJWT checks `exp`, `nbf` and `iat` against, shifted by `offset`."""

    offset = timedelta(0)

    @classmethod
    def now(cls, tz: Any = None) -> JwtClock:
        shifted = datetime.now(tz or UTC) + cls.offset
        return cls.fromtimestamp(shifted.timestamp(), tz=shifted.tzinfo)


@pytest.fixture
def jwt_clock(monkeypatch: pytest.MonkeyPatch) -> type[JwtClock]:
    """Shift the time PyJWT verifies tokens against; `make_token` is unaffected."""
    # A fresh subclass per test, so an offset never leaks into another test.
    clock = type("ShiftedClock", (JwtClock,), {"offset": timedelta(0)})
    monkeypatch.setattr(jwt.api_jwt, "datetime", clock)
    return clock
