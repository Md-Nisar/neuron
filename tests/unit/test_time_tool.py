from __future__ import annotations

from datetime import UTC, datetime, timedelta

from neuron_agent.tools.time import utc_now


def test_utc_now_returns_the_current_time_in_utc_iso_format() -> None:
    parsed = datetime.fromisoformat(utc_now.invoke({}))
    assert parsed.utcoffset() == timedelta(0)
    assert abs(datetime.now(tz=UTC) - parsed) < timedelta(seconds=5)
