"""`/v1/me/threads?limit=` takes an integer only: the SQL-injection payloads ZAP sent are refused
before any query runs (the excused DAST alert in `deploy/reference/zap-rules.tsv`, #331)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.conftest import JwtApi, bearer


@pytest.fixture
def api(jwt_api_factory: Callable[..., JwtApi]) -> JwtApi:
    return jwt_api_factory()


@pytest.mark.parametrize(
    "limit", ["50 AND 1=1 -- ", "50 OR 1=1 -- ", "50' OR '1'='1", "0", "101", "-1", "1e2"]
)
def test_a_non_integer_or_out_of_range_limit_is_refused(
    api: JwtApi, make_token: Callable[..., str], limit: str
) -> None:
    response = api.client.get(
        "/v1/me/threads", params={"limit": limit}, headers=bearer(make_token("alice"))
    )

    assert response.status_code == 422
