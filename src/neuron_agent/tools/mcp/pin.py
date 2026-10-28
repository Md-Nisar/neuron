# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""`neuron-mcp-pin`: print the `APP_MCP_SERVERS` entry for a server, to review and commit.

It connects once, lists the server's tools and prints each tool's description (stderr, for you
to read) and its pin (stdout, as a config entry with the safe default risk `mutating`). Pinning
is the review step: read the descriptions before you keep a tool in the file.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

from pydantic import SecretStr

from neuron_agent.tools.mcp.client import fetch_definitions_blocking
from neuron_agent.tools.mcp.config import McpToolConfig
from neuron_agent.tools.mcp.pins import tool_pin
from neuron_agent.tools.mcp.urls import validate_mcp_url


def _printable(text: str) -> str:
    """`text` with control, format (bidirectional, zero-width) and unassigned characters escaped.

    A server's name and description are untrusted and are shown on a terminal: an escape
    sequence could rewrite what the operator is reviewing.
    """
    return "".join(
        char
        if char in "\n\t" or not unicodedata.category(char).startswith("C")
        else char.encode("unicode_escape").decode("ascii")
        for char in text
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="neuron-mcp-pin", description=__doc__)
    parser.add_argument("url", help="the server's Streamable HTTP endpoint")
    parser.add_argument("--name", default="server", help="the server name for the entry")
    parser.add_argument("--token-file", type=Path, help="file holding the bearer token")
    parser.add_argument(
        "--env",
        choices=["development", "test", "staging", "production"],
        default="development",
        help="applies the URL rules of this environment (loopback http only in development/test)",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds to wait")
    args = parser.parse_args(argv)

    url = validate_mcp_url(args.url, env=args.env)
    token = (
        SecretStr(args.token_file.read_text(encoding="utf-8").strip()) if args.token_file else None
    )
    definitions = fetch_definitions_blocking(url, token=token, env=args.env, timeout=args.timeout)
    tools = []
    for definition in definitions:
        name = _printable(definition.name)
        description = _printable(definition.description or "(no description)")
        if (name, description) != (definition.name, definition.description or "(no description)"):
            print(
                f"!!! {name}: control characters were escaped below; look closely", file=sys.stderr
            )
        print(
            f"--- {name}\n{description}",
            file=sys.stderr,
        )
        tools.append({"name": definition.name, "pin": tool_pin(definition), "risk": "mutating"})
        # A tool whose name the config would refuse is shown, not hidden.
        try:
            McpToolConfig.model_validate(tools[-1])
        except ValueError:
            print(f"!!! {name}: the name is not allowed in the config", file=sys.stderr)
    entry = {
        "name": args.name,
        "url": url,
        "auth": "bearer" if token else "none",
        "tools": tools,
    }
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
