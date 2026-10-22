# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The `neuron-api` entrypoint (issue #135, ADR 0008 decision 3)."""

from __future__ import annotations

import logging
import re
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import structlog
import uvicorn
from fastapi import FastAPI, Request
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.observability.telemetry import instrument_app

SRC = Path("src/neuron_agent")
# The only files allowed to touch the process environment (AGENTS.md).
ENV_ALLOWED = {
    "config/settings.py",
    "observability/langsmith_governance.py",
    "observability/telemetry.py",
}
FORGED = "203.0.113.99"
PUBLIC = "0.0.0.0"  # noqa: S104


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("APP_ENV", "APP_HOST", "APP_PORT", "PORT"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _settings(**values: Any) -> Settings:
    """Settings from the process environment and `values` only, never a developer's `.env`."""
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_no_environment_access_outside_the_documented_files() -> None:
    pattern = re.compile(r"\bos\.(getenv|environ|putenv|unsetenv)\b|\bfrom os import\b.*env")
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in SRC.rglob("*.py")
        if path.relative_to(SRC).as_posix() not in ENV_ALLOWED
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


def test_host_and_port_default_to_loopback_8000(clean_env: pytest.MonkeyPatch) -> None:
    config = _settings()
    assert (config.host, config.port) == ("127.0.0.1", 8000)


def test_port_is_read_from_app_port_or_render_port(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_PORT", "9000")
    assert _settings().port == 9000
    # Render's PORT wins over the image's APP_PORT default.
    clean_env.setenv("PORT", "10000")
    assert _settings().port == 10000


def test_uvicorn_options_come_from_settings() -> None:
    options = api_main.uvicorn_options(
        Settings(env="test", host=PUBLIC, port=9100, run_timeout_seconds=45)
    )
    assert options == {
        "app": "neuron_agent.api.main:app",
        "host": PUBLIC,
        "port": 9100,
        "timeout_graceful_shutdown": 55,
        "proxy_headers": False,
        "reload": False,
    }
    assert "workers" not in options


def test_reload_is_for_loopback_development_only() -> None:
    assert api_main.uvicorn_options(Settings(env="development"))["reload"] is True
    assert api_main.uvicorn_options(Settings(env="development", host=PUBLIC))["reload"] is False


def test_main_refuses_a_public_bind_without_an_explicit_app_env(
    clean_env: pytest.MonkeyPatch,
) -> None:
    ran: list[dict[str, Any]] = []
    clean_env.setattr(uvicorn, "run", lambda **kwargs: ran.append(kwargs))
    clean_env.setattr(api_main, "settings", _settings(host=PUBLIC))

    with pytest.raises(SystemExit) as exit_info:
        api_main.main()

    assert exit_info.value.code not in (0, None)
    assert "APP_ENV" in str(exit_info.value.code)
    assert ran == []


def test_main_starts_on_a_public_bind_with_an_explicit_app_env(
    clean_env: pytest.MonkeyPatch,
) -> None:
    ran: list[dict[str, Any]] = []
    clean_env.setattr(uvicorn, "run", lambda **kwargs: ran.append(kwargs))
    clean_env.setenv("APP_ENV", "test")
    clean_env.setenv("APP_HOST", PUBLIC)
    clean_env.setattr(api_main, "settings", _settings())

    api_main.main()

    assert [(run["host"], run["port"]) for run in ran] == [(PUBLIC, 8000)]


def test_main_starts_on_loopback_without_an_explicit_app_env(
    clean_env: pytest.MonkeyPatch,
) -> None:
    ran: list[dict[str, Any]] = []
    clean_env.setattr(uvicorn, "run", lambda **kwargs: ran.append(kwargs))
    clean_env.setattr(api_main, "settings", _settings())

    api_main.main()

    assert len(ran) == 1


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@contextmanager
def _serve(app: FastAPI) -> Iterator[str]:
    """Serve `app` with the options `main()` builds, on an ephemeral loopback port."""
    options = {**api_main.uvicorn_options(Settings(env="test")), "app": app, "port": 0}
    server = uvicorn.Server(uvicorn.Config(**{**options, "reload": False}))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _app_reporting_client_ip(exporter: InMemorySpanExporter) -> FastAPI:
    app = FastAPI()
    log = structlog.get_logger("test")

    @app.get("/ip")
    async def ip(request: Request) -> dict[str, str]:
        key = api_main._client_ip(request)
        log.info("request_seen", client=key)
        return {"key": key}

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrument_app(app, tracer_provider=provider, meter_provider=MeterProvider())
    return app


def _get(url: str, forwarded_for: str) -> str:
    request = urllib.request.Request(  # noqa: S310
        url + "/ip", headers={"X-Forwarded-For": forwarded_for}
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return str(response.read().decode())


def test_trusted_proxy_is_keyed_by_the_forwarded_address_through_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["127.0.0.0/8"])
    with _serve(_app_reporting_client_ip(InMemorySpanExporter())) as url:
        assert _get(url, "198.51.100.7") == '{"key":"198.51.100.7"}'


def test_untrusted_peer_is_keyed_by_the_peer_and_a_forged_header_leaks_nowhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", [])
    exporter = InMemorySpanExporter()
    access = _Capture()
    with (
        structlog.testing.capture_logs() as logs,
        _serve(_app_reporting_client_ip(exporter)) as url,
    ):
        uvicorn_access = logging.getLogger("uvicorn.access")
        uvicorn_access.addHandler(access)
        try:
            body = _get(url, FORGED)
        finally:
            uvicorn_access.removeHandler(access)

    assert body == '{"key":"127.0.0.1"}'
    assert access.lines, "the access log captured nothing, so the check below proves nothing"
    spans = exporter.get_finished_spans()
    assert spans
    seen = [str(logs), *access.lines]
    for span in spans:
        seen.append(span.name)
        seen.extend(f"{key}={value}" for key, value in (span.attributes or {}).items())
    assert not [text for text in seen if FORGED in text]
