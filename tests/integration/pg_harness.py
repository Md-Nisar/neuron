"""Two Uvicorn processes against one Postgres, for the cross-replica guard tests (#146).

`AppProcess` starts the real app (`pg_harness_app.py`) in its own process. The database is
passed in `APP_POSTGRES_DSN` (an environment variable, never an argument, so it cannot show in
a process list) and every other setting through `settings`. Reuse it for the rate limiter and
the token budget (#147, #148): start two `AppProcess`es on one `database`, and drive both.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess  # nosec B404 - runs this repo's own app
import sys
import time
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).parent
_STARTUP_SECONDS = 60.0
_FOREIGN = ("APP_", "OPENAI", "NVIDIA")


# Every process started, so a test that fails between two starts cannot orphan one (the
# `reap_app_processes` fixture closes whatever is left).
LIVE: list[AppProcess] = []


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class AppProcess:
    """One app process; `settings` are `APP_*` names without the prefix, in lower case."""

    def __init__(self, dsn: str, log_dir: Path, name: str, **settings: Any) -> None:
        self.name = name
        self.port = _free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith(_FOREIGN)}
        env.update(
            APP_ENV="test",
            APP_CHECKPOINTER="postgres",
            APP_LIMITS_BACKEND="postgres",
            APP_POSTGRES_DSN=dsn,
            APP_RATE_LIMIT_ENABLED="false",
            APP_OTEL_ENABLED="false",
            APP_ENABLE_LANGSMITH="false",
            APP_MAX_CONCURRENT_RUNS_PER_USER="1000",
            PYTHONPATH=os.pathsep.join([str(HERE), env.get("PYTHONPATH", "")]),
        )
        env.update({f"APP_{key.upper()}": str(value) for key, value in settings.items()})
        self._log = (log_dir / f"{name}.log").open("wb")
        self._process = subprocess.Popen(  # noqa: S603  # nosec B603
            [
                sys.executable,
                "-m",
                "uvicorn",
                "pg_harness_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            env=env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )
        self._client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{self.port}", timeout=120)
        LIVE.append(self)

    async def wait_ready(self) -> AppProcess:
        deadline = time.monotonic() + _STARTUP_SECONDS
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(f"{self.name} exited with {self._process.returncode}")
            try:
                if (await self._client.get("/health/ready", timeout=2)).status_code == 200:
                    return self
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        raise TimeoutError(f"{self.name} did not become ready")

    async def invoke(self, message: str = "ok", **body: Any) -> httpx.Response:
        return await self._client.post("/v1/agent/invoke", json={"message": message, **body})

    async def get(self, path: str, *, user_id: str) -> httpx.Response:
        return await self._client.get(path, headers={"X-User-Id": user_id})

    def kill(self) -> None:
        """SIGKILL: the process gets no chance to release its leases."""
        self._process.send_signal(signal.SIGKILL)
        self._process.wait(timeout=10)

    def stop_now(self) -> None:
        """Stop the process and close its log without an event loop; safe to call again."""
        if self._process.poll() is None:
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)
        self._log.close()

    async def close(self) -> None:
        """Stop the process and release its resources; safe to call again."""
        await self._client.aclose()
        self.stop_now()
