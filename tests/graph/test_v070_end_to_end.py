"""The v0.7.0 release walk-through with fakes (#251): remember, approve, a new thread, recall,
convert units through MCP, export and erase. The model is scripted; everything else is real."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from scripts import mcp_reference_server as reference
from tests.conftest import JwtApi, StreamingFakeModel, bearer
from tests.unit.test_mcp_client import _pins, serve

from neuron_agent.agents.factory import build_registry
from neuron_agent.models import factory

_SCOPES = (
    "agent:invoke agent:approve threads:read threads:delete memories:read memories:write "
    "tools:remember tools:recall tools:forget tools:mcp.units.convert_units"
)
_NOTE = "my locker code is 4417-sigma"  # noqa: S105 - test text, not a credential


def _call(name: str, args: dict[str, object], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_remember_approve_recall_convert_export_erase(
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    replies = iter(
        [
            _call("remember", {"text": _NOTE}, "c1"),
            AIMessage(content="Saved."),
            _call("recall", {}, "c2"),
            AIMessage(content="Your locker code is 4417-sigma."),
            _call(
                "mcp_units_convert_units",
                {"value": 2, "from_unit": "kg", "to_unit": "lb"},
                "c3",
            ),
            AIMessage(content="About 4.4 lb."),
        ]
    )
    monkeypatch.setattr(
        factory, "create_chat_model", lambda _: StreamingFakeModel(messages=replies)
    )

    with serve(reference.build_app()) as url:
        pins = asyncio.run(_pins(url))
        entry = {
            "name": "units",
            "url": url,
            "auth": "none",
            "tools": [{"name": n, "pin": p, "risk": "read"} for n, p in pins.items()],
        }
        servers = tmp_path / "mcp.json"
        servers.write_text(json.dumps({"servers": [entry]}), encoding="utf-8")
        api = jwt_api_factory(memory_enabled=True, mcp_servers=servers)
        registry = asyncio.run(build_registry(api.settings))
        assert registry is not None
        api.service.use_registry(registry)
        asyncio.run(api.service.startup())
        token = make_token("alice", scopes=_SCOPES)
        headers = bearer(token)

        # 1. remember pauses for approval, and nothing is stored until the user approves.
        paused = api.client.post(
            "/v1/agent/invoke", json={"message": f"remember that {_NOTE}"}, headers=headers
        ).json()
        assert paused["status"] == "approval_required"
        assert api.client.get("/v1/me/memories", headers=headers).json()["total"] == 0

        # 2. approve: the note is stored.
        done = api.client.post(
            f"/v1/threads/{paused['thread_id']}/approvals/{paused['approval']['approval_id']}",
            json={"decision": "approve"},
            headers=headers,
        ).json()
        assert done["status"] == "completed"
        stored = api.client.get("/v1/me/memories", headers=headers).json()
        assert [m["text"] for m in stored["memories"]] == [_NOTE]

        # 3. a new thread recalls it (recall is a read tool, so it does not pause).
        recalled = api.client.post(
            "/v1/agent/invoke", json={"message": "what is my locker code?"}, headers=headers
        ).json()
        assert recalled["thread_id"] != paused["thread_id"]
        assert recalled["used_tools"] == ["recall"]
        assert "4417-sigma" in recalled["answer"]

        # 4. unit conversion through the pinned MCP server.
        converted = api.client.post(
            "/v1/agent/invoke", json={"message": "2 kg in lb?"}, headers=headers
        ).json()
        assert converted["used_tools"] == ["mcp_units_convert_units"]

    # 5. export carries the memory; erase removes memory and threads.
    export = api.client.get("/v1/me/export", headers=headers).json()
    assert [m["text"] for m in export["memories"]] == [_NOTE]
    erased = api.client.delete("/v1/me/threads", headers=headers).json()
    assert erased["erased_memory_count"] == 1
    assert api.client.get("/v1/me/memories", headers=headers).json()["total"] == 0
