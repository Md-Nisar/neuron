# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A small MCP server for tests, evals and local runs (ADR 0009, decision 5).

It offers one read-only tool, `convert_units`, over Streamable HTTP on loopback, so the MCP path
can be exercised offline. It is a development aid, not part of the service image.

    uv run python scripts/mcp_reference_server.py            # http://127.0.0.1:8765/mcp
    uv run python scripts/mcp_reference_server.py --token-file ./token --port 9000

`neuron-mcp-pin` prints the entry to put in `APP_MCP_SERVERS` for a running server.
"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Units grouped by what they measure, each with its size in the group's base unit.
_LINEAR: dict[str, dict[str, float]] = {
    "length": {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0, "in": 0.0254, "ft": 0.3048,
               "yd": 0.9144, "mi": 1609.344},
    "mass": {"mg": 1e-6, "g": 0.001, "kg": 1.0, "oz": 0.028349523125, "lb": 0.45359237},
    "volume": {"ml": 0.001, "l": 1.0, "gal": 3.785411784, "qt": 0.946352946, "cup": 0.2365882365},
}  # fmt: skip
_TEMPERATURE = {"c", "f", "k"}


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert `value`; raises ValueError for unknown units or units of different kinds."""
    source, target = from_unit.strip().lower(), to_unit.strip().lower()
    if source in _TEMPERATURE and target in _TEMPERATURE:
        kelvin = {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[source]
        return {"c": kelvin - 273.15, "f": (kelvin - 273.15) * 9 / 5 + 32, "k": kelvin}[target]
    for units in _LINEAR.values():
        if source in units and target in units:
            return value * units[source] / units[target]
    raise ValueError(f"cannot convert {from_unit!r} to {to_unit!r}")


def build_server() -> MCPServer:
    server = MCPServer("units")

    @server.tool()
    def convert_units(value: float, from_unit: str, to_unit: str) -> str:
        """Convert a number between units of length, mass, volume or temperature."""
        result = convert(value, from_unit, to_unit)
        return f"{value:g} {from_unit} = {result:.6g} {to_unit}"

    return server


_Scope = MutableMapping[str, Any]
_Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
_Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class RequireBearer:
    """ASGI wrapper: 401 unless the request carries `Authorization: Bearer <token>`."""

    def __init__(self, app: Any, token: str, seen: list[str] | None = None) -> None:
        self._app = app
        self._expected = f"Bearer {token}"
        # Test hook: the Authorization header of every request, so a test can check what was sent.
        self.seen = seen if seen is not None else []

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope["type"] == "http":
            header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
            self.seen.append(header)
            if header != self._expected:
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b""})
                return
        await self._app(scope, receive, send)


def build_app(token: str | None = None) -> Any:
    app = build_server().streamable_http_app()
    return RequireBearer(app, token) if token else app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token-file", type=Path, help="require this bearer token")
    args = parser.parse_args()
    token = args.token_file.read_text(encoding="utf-8").strip() if args.token_file else None
    uvicorn.run(build_app(token), host=HOST, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
