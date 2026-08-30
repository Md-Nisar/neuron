from __future__ import annotations

from fastapi.testclient import TestClient

from neuron_agent.api.main import app


def test_live_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_invoke_rejects_empty_message() -> None:
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": ""})
    assert response.status_code == 422
