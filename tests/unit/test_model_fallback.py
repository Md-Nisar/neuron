"""Model fallback chain (#235, ADR 0009 decision 3): `APP_FALLBACK_MODELS`."""

from __future__ import annotations

from typing import Any

import pytest
import structlog.testing
from langchain.agents.middleware import ModelFallbackMiddleware, ModelRetryMiddleware
from langchain_core.exceptions import ModelNotFoundError
from langchain_core.messages import AIMessage, HumanMessage
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from pydantic import SecretStr, ValidationError
from tests.conftest import StreamingFakeModel

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ConfigurationError
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.models import factory
from neuron_agent.observability import metrics, semconv
from neuron_agent.security.authorization import AuthorizationContext

pytestmark = pytest.mark.anyio

_PRIMARY = "nvidia:primary-model"
_FALLBACKS = ["anthropic:backup-one", "openai:backup-two"]
_PRIVATE_TEXT = "my-private-question-0451"


def _settings(**overrides: Any) -> Settings:
    return Settings(env="test", default_model=_PRIMARY, **overrides)


class _FailingModel(StreamingFakeModel):
    """Every way of calling it raises the provider-neutral 404."""

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        raise ModelNotFoundError("404 model not found for this account")

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        raise ModelNotFoundError("404 model not found for this account")

    def _stream(self, *args: Any, **kwargs: Any) -> Any:
        raise ModelNotFoundError("404 model not found for this account")

    async def _astream(self, *args: Any, **kwargs: Any) -> Any:
        raise ModelNotFoundError("404 model not found for this account")
        yield  # pragma: no cover


def _install_models(monkeypatch: pytest.MonkeyPatch, models: dict[str, Any]) -> None:
    def create(_: Settings, identifier: str | None = None) -> Any:
        return models[identifier or _PRIMARY]

    monkeypatch.setattr(factory, "create_chat_model", create)


def _replies(*texts: str) -> StreamingFakeModel:
    return StreamingFakeModel(messages=iter([AIMessage(content=text) for text in texts]))


@pytest.fixture
def metric_reader(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=metrics.metric_views())
    monkeypatch.setattr(metrics, "_meter", lambda: provider.get_meter("test"))
    return reader


def _fallback_points(reader: InMemoryMetricReader) -> list[Any]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == semconv.METRIC_MODEL_FALLBACKS
        for point in metric.data.data_points
    ]


def test_no_fallback_by_default() -> None:
    assert Settings(env="test").fallback_models == []
    middleware = factory.agent_middleware(_settings())
    assert not any(isinstance(m, ModelFallbackMiddleware) for m in middleware)


def test_fallback_sits_directly_outside_the_provider_retries() -> None:
    middleware = factory.agent_middleware(_settings(fallback_models=_FALLBACKS))
    kinds = [type(m) for m in middleware]
    retry = next(i for i, m in enumerate(middleware) if isinstance(m, ModelRetryMiddleware))
    fallback = next(i for i, m in enumerate(middleware) if isinstance(m, ModelFallbackMiddleware))
    assert fallback == retry - 1, kinds
    # Authorization, usage accounting and tracing wrap every attempt.
    assert kinds.index(factory._TracingMiddleware) < fallback
    assert kinds.index(factory._ToolAuthorizationMiddleware) < fallback


@pytest.mark.parametrize(
    "value",
    [
        ["gpt-5"],
        ["mistral:large"],
        ["openai:"],
        [_PRIMARY],
        ["openai:a", "openai:a"],
        ["openai:a"] * 4,
    ],
)
def test_invalid_fallback_lists_are_refused(value: list[str]) -> None:
    with pytest.raises(ValidationError):
        _settings(fallback_models=value)


def test_staging_and_production_need_a_key_for_every_fallback_provider() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(
            env="staging",
            default_model="openai:gpt-5.4-mini",
            openai_api_key=SecretStr("sk-test"),
            fallback_models=["anthropic:backup"],
        )


def test_the_fallback_list_is_read_from_the_environment_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_FALLBACK_MODELS", '["anthropic:a", "openai:b"]')
    assert Settings(env="test").fallback_models == ["anthropic:a", "openai:b"]


async def test_a_404_on_the_primary_falls_back_and_is_counted_without_content(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    _install_models(
        monkeypatch,
        {
            _PRIMARY: _FailingModel(messages=iter([])),
            **dict.fromkeys(_FALLBACKS, _replies("from backup")),
        },
    )
    graph = build_graph(_settings(fallback_models=_FALLBACKS))

    with structlog.testing.capture_logs() as logs:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=_PRIVATE_TEXT)]},
            context=AuthorizationContext(frozenset()),
        )

    assert result["answer"].answer == "from backup"
    [point] = _fallback_points(metric_reader)
    assert point.value == 1
    assert dict(point.attributes) == {
        semconv.NEURON_FALLBACK_FROM: _PRIMARY,
        semconv.NEURON_FALLBACK_TO: _FALLBACKS[0],
    }
    [event] = [entry for entry in logs if entry["event"] == "model_fallback"]
    assert (event["from_model"], event["to_model"]) == (_PRIMARY, _FALLBACKS[0])
    assert _PRIVATE_TEXT not in str(logs)


async def test_the_chain_continues_to_the_next_fallback(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    _install_models(
        monkeypatch,
        {
            _PRIMARY: _FailingModel(messages=iter([])),
            _FALLBACKS[0]: _FailingModel(messages=iter([])),
            _FALLBACKS[1]: _replies("from the last one"),
        },
    )
    graph = build_graph(_settings(fallback_models=_FALLBACKS))

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="hi")]}, context=AuthorizationContext(frozenset())
    )

    assert result["answer"].answer == "from the last one"
    assert sorted(
        dict(p.attributes)[semconv.NEURON_FALLBACK_TO] for p in _fallback_points(metric_reader)
    ) == sorted(_FALLBACKS)


async def test_a_healthy_primary_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    _install_models(
        monkeypatch,
        {_PRIMARY: _replies("primary answer"), **dict.fromkeys(_FALLBACKS, _replies("unused"))},
    )
    graph = build_graph(_settings(fallback_models=_FALLBACKS))

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="hi")]}, context=AuthorizationContext(frozenset())
    )

    assert result["answer"].answer == "primary answer"
    assert _fallback_points(metric_reader) == []


async def test_when_every_model_fails_the_error_is_classified_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = {m: _FailingModel(messages=iter([])) for m in (_PRIMARY, *_FALLBACKS)}
    _install_models(monkeypatch, failing)
    graph = build_graph(_settings(fallback_models=_FALLBACKS))

    with pytest.raises(ConfigurationError):
        await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]}, context=AuthorizationContext(frozenset())
        )


def test_neuron_eval_refuses_a_fallback_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neuron_agent.config.settings import get_settings
    from neuron_agent.evaluation import main

    monkeypatch.setenv("APP_FALLBACK_MODELS", '["openai:backup"]')
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="APP_FALLBACK_MODELS"):
            main(["--suite", "single_turn"])
    finally:
        get_settings.cache_clear()
