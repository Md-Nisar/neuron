from __future__ import annotations

import time

import pytest
from pydantic import ValidationError
from tests.conftest import PRODUCTION_PROFILE

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import create_chat_model

pytestmark = pytest.mark.anyio


def _fake(**overrides: object) -> Settings:
    return Settings(_env_file=None, env="test", **overrides)  # type: ignore[call-arg, arg-type]


async def _stream(settings: Settings) -> tuple[float, int, float]:
    model = create_chat_model(settings)
    start = time.perf_counter()
    first = 0.0
    count = 0
    async for _ in model.astream("hi"):
        if count == 0:
            first = time.perf_counter() - start
        count += 1
    return first, count, time.perf_counter() - start


async def test_default_fake_model_answers_instantly() -> None:
    first, _, total = await _stream(_fake())
    assert total < 0.2
    assert first < 0.2


async def test_stream_shows_time_to_first_token_and_token_count() -> None:
    settings = _fake(
        fake_model_ttft_ms=200, fake_model_tokens_per_second=100, fake_model_output_tokens=10
    )
    first, count, total = await _stream(settings)
    assert count == 10
    assert 0.18 <= first < 0.5
    assert 0.27 <= total < 0.8  # 200 ms to first token, then 9 gaps of 10 ms


def test_invoke_waits_for_the_whole_answer() -> None:
    settings = _fake(
        fake_model_ttft_ms=100, fake_model_tokens_per_second=100, fake_model_output_tokens=10
    )
    start = time.perf_counter()
    answer = create_chat_model(settings).invoke("hi")
    assert time.perf_counter() - start >= 0.19
    assert str(answer.content).split() == ["token"] * 10


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize(
    "override",
    [
        {"fake_model_ttft_ms": 1},
        {"fake_model_tokens_per_second": 1},
        {"fake_model_output_tokens": 1},
    ],
)
def test_latency_settings_are_refused_in_staging_and_production(
    env: str, override: dict[str, int]
) -> None:
    with pytest.raises(ValidationError, match="APP_FAKE_MODEL"):
        Settings(
            env=env,  # type: ignore[arg-type]
            auth_mode="jwt",
            auth_issuer="https://issuer.example.test",
            auth_audience="neuron-api",
            auth_jwks_url="https://issuer.example.test/.well-known/jwks.json",
            identity_hash_key="x" * 32,
            openai_api_key="sk-test",  # type: ignore[arg-type]
            **PRODUCTION_PROFILE,
            **override,
        )


@pytest.mark.parametrize(
    "override",
    [
        {"fake_model_ttft_ms": 10_001},
        {"fake_model_tokens_per_second": 1_001},
        {"fake_model_output_tokens": 0},
        {"fake_model_output_tokens": 2_001},
    ],
)
def test_latency_settings_are_bounded(override: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        _fake(**override)


async def test_remember_turn_calls_the_memory_tool_when_shaped_and_bound() -> None:
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool

    @tool
    def remember(text: str) -> str:
        """Remember a note."""
        return text

    model = create_chat_model(_fake(fake_model_output_tokens=5)).bind_tools([remember])
    message = await model.ainvoke([HumanMessage("remember: buy milk")])
    assert message.tool_calls[0]["name"] == "remember"
    assert message.tool_calls[0]["args"] == {"text": "buy milk"}


async def test_remember_turn_is_plain_text_without_the_tool_or_the_profile() -> None:
    from langchain_core.messages import HumanMessage

    shaped = create_chat_model(_fake(fake_model_output_tokens=3))  # tool not bound
    assert not (await shaped.ainvoke([HumanMessage("remember: x")])).tool_calls
    plain = create_chat_model(_fake())
    assert not (await plain.ainvoke([HumanMessage("remember: x")])).tool_calls
