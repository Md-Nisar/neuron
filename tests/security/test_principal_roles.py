"""Roles come only from the verified token (RAG-09.02, ADR 0006 amendment).

End to end through the HTTP API and the real verifier: a `roles` field in a body is refused,
and a roles header changes nothing; the run's authorization context carries the token's roles.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.conftest import JwtApi, bearer

from neuron_agent.security.authorization import AuthorizationContext


def _record_contexts(api: JwtApi, monkeypatch: pytest.MonkeyPatch) -> list[AuthorizationContext]:
    contexts: list[AuthorizationContext] = []
    build = api.service._authorization

    def recording(*args: object, **kwargs: object) -> AuthorizationContext:
        context = build(*args, **kwargs)  # type: ignore[arg-type]
        contexts.append(context)
        return context

    monkeypatch.setattr(api.service, "_authorization", recording)
    return contexts


def test_the_run_context_carries_the_tokens_roles(
    jwt_api: JwtApi, make_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: roles in the run's context equal the configured claim's values."""
    contexts = _record_contexts(jwt_api, monkeypatch)
    response = jwt_api.client.post(
        "/v1/agent/invoke",
        headers=bearer(make_token(roles=["finance", "legal"])),
        json={"message": "hello"},
    )
    assert response.status_code == 200, response.text
    assert [context.roles for context in contexts] == [frozenset({"finance", "legal"})]


@pytest.mark.parametrize("field", ["roles", "role", "groups"])
def test_a_roles_field_in_the_body_is_refused(
    jwt_api: JwtApi, make_token: Callable[..., str], field: str
) -> None:
    """AC3: request bodies cannot carry roles."""
    response = jwt_api.client.post(
        "/v1/agent/invoke",
        headers=bearer(make_token()),
        json={"message": "hello", field: ["admin"]},
    )
    assert response.status_code == 422


def test_roles_headers_have_no_effect(
    jwt_api: JwtApi, make_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: a header naming roles neither adds to nor replaces the token's roles."""
    contexts = _record_contexts(jwt_api, monkeypatch)
    headers = {
        **bearer(make_token(roles=["finance"])),
        "X-Roles": "admin",
        "X-User-Roles": "admin",
        "X-Groups": "admin",
    }
    response = jwt_api.client.post("/v1/agent/invoke", headers=headers, json={"message": "hello"})
    assert response.status_code == 200, response.text
    assert [context.roles for context in contexts] == [frozenset({"finance"})]
