"""MCP tools in the running service (#239): registry build, dev permissions, the pin command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from scripts import mcp_reference_server as reference
from tests.conftest import StreamingFakeModel
from tests.unit.test_mcp_client import _pins, serve

from neuron_agent.agents.factory import build_registry
from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.models import factory
from neuron_agent.services.agent_service import AgentService
from neuron_agent.tools.mcp import pin as pin_command
from neuron_agent.tools.mcp.pins import FetchedTool

pytestmark = pytest.mark.anyio


async def _settings_for(url: str, tmp_path: Path, **overrides: Any) -> Settings:
    pins = await _pins(url)
    entry = {
        "name": "units",
        "url": url,
        "auth": "none",
        "tools": [{"name": n, "pin": p, "risk": "read"} for n, p in pins.items()],
    }
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": [entry]}), encoding="utf-8")
    return Settings(env="test", mcp_servers=path, **overrides)


async def test_without_servers_the_registry_is_the_builtin_one() -> None:
    assert await build_registry(Settings(env="test")) is None


async def test_with_servers_the_registry_adds_the_pinned_tools(tmp_path: Path) -> None:
    with serve(reference.build_app()) as url:
        registry = await build_registry(await _settings_for(url, tmp_path))
    assert registry is not None
    assert registry.names() == ("utc_now", "calculator", "mcp_units_convert_units")


async def test_a_bad_file_stops_start_up(tmp_path: Path) -> None:
    from neuron_agent.errors.base import ConfigurationError

    path = tmp_path / "mcp.json"
    path.write_text('{"servers": [{"name": "x", "command": "npx"}]}', encoding="utf-8")
    with pytest.raises(ConfigurationError):
        await build_registry(Settings(env="test", mcp_servers=path))


async def test_the_service_serves_mcp_tools_and_development_grants_their_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = {
        "name": "mcp_units_convert_units",
        "args": {"value": 2, "from_unit": "kg", "to_unit": "lb"},
        "id": "call-1",
    }
    replies = [AIMessage(content="", tool_calls=[call]), AIMessage(content="about 4.4 lb")]
    monkeypatch.setattr(
        factory, "create_chat_model", lambda _: StreamingFakeModel(messages=iter(replies))
    )
    with serve(reference.build_app()) as url:
        settings = await _settings_for(url, tmp_path)
        service = AgentService(settings)
        registry = await build_registry(settings)
        assert registry is not None
        service.use_registry(registry)
        await service.startup()
        monkeypatch.setattr(api_main, "service", service)

        response = TestClient(app).post("/v1/agent/invoke", json={"message": "2 kg in lb?"})

    assert response.status_code == 200, response.text
    assert response.json()["used_tools"] == ["mcp_units_convert_units"]


async def test_the_pin_command_prints_a_reviewable_entry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with serve(reference.build_app()) as url:
        expected = await _pins(url)
        # `main` runs its own event loop, so it runs in a worker thread here.
        await anyio.to_thread.run_sync(pin_command.main, [url, "--name", "units"])

    captured = capsys.readouterr()
    entry = json.loads(captured.out)
    assert entry["name"] == "units"
    assert entry["auth"] == "none"
    assert entry["tools"] == [
        {"name": "convert_units", "pin": expected["convert_units"], "risk": "mutating"}
    ]
    assert "Convert a number between units" in captured.err
    # The schema is pinned and read by the model, so the operator reviews it too.
    assert '"from_unit"' in captured.err


def test_a_server_cannot_rewrite_the_operators_terminal() -> None:
    hostile = "ok\x1b[2J\x1b[1;1Hnothing to see‮​\r"
    shown = pin_command._printable(hostile)
    assert "\x1b" not in shown
    assert "\r" not in shown
    assert "‮" not in shown
    assert "​" not in shown
    assert "\\x1b" in shown
    assert pin_command._printable("line one\n\tline two") == "line one\n\tline two"


def test_a_schema_cannot_rewrite_the_operators_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = FetchedTool(
        "t", "ok", {"type": "object", "properties": {"a": {"description": "x\x1b[2J\u202e"}}}
    )
    monkeypatch.setattr(pin_command, "fetch_definitions_blocking", lambda *_, **__: [hostile])

    pin_command.main(["http://127.0.0.1:9/mcp"])

    err = capsys.readouterr().err
    assert "\x1b" not in err
    assert "\u202e" not in err
    assert "\\u001b[2J\\u202e" in err
