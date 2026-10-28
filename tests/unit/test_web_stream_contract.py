"""The web client's stream types stay in step with the server (ADR 0010, decision 4).

`web/src/lib/stream/contract.json` is read by the client's Vitest suite and checked here
against the real response models and event list. If a server field or event changes, this
test fails until the fixture, and with it the client, is updated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from neuron_agent.schemas.agent import (
    AgentResponse,
    ApprovalRequest,
    ApprovalRequiredResponse,
    PendingAction,
)
from neuron_agent.services.streaming import STREAM_PROTOCOL_VERSION, StreamEventType

_FIXTURE = Path(__file__).resolve().parents[2] / "web/src/lib/stream/contract.json"


def _fixture() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return loaded


def test_the_client_knows_the_servers_protocol_version_and_exact_event_set() -> None:
    fixture = _fixture()

    assert fixture["protocol_version"] == STREAM_PROTOCOL_VERSION
    assert fixture["events"] == list(get_args(StreamEventType))


def test_the_final_payload_is_what_the_server_sends() -> None:
    response = AgentResponse(
        request_id="r1", thread_id="t1", answer="57", used_tools=["calculator"], confidence=0.9
    )

    assert _fixture()["payloads"]["final"] == response.model_dump()  # type: ignore[index]


def test_the_approval_payload_is_what_the_server_sends() -> None:
    response = ApprovalRequiredResponse(
        request_id="r1",
        thread_id="t1",
        approval=ApprovalRequest(
            approval_id="a1",
            actions=[PendingAction(name="remember", args={"text": "likes tea"})],
            allowed_decisions=["approve", "reject"],
        ),
    )

    assert _fixture()["payloads"]["approval_required"] == response.model_dump()  # type: ignore[index]
