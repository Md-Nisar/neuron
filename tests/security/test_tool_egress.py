"""No tool reaches the network except through the SSRF helper (ADR 0008 decision 12)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import neuron_agent.tools as tools_package
from neuron_agent.agents import factory as agent_factory
from neuron_agent.config.settings import Settings

_TOOLS_DIR = Path(tools_package.__file__).parent
_NETWORK_MODULES = {
    "httpx", "requests", "aiohttp", "urllib3", "socket", "http", "urllib", "ftplib", "smtplib",
    "websockets", "subprocess", "langchain_community",
}  # fmt: skip
_HELPER = "validate_safe_url"


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _calls_helper(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == _HELPER)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == _HELPER)
        )
        for node in ast.walk(tree)
    )


def _violations(directory: Path) -> list[str]:
    found = []
    for path in sorted(directory.rglob("*.py")):
        tree = ast.parse(path.read_text())
        if _imported_roots(tree) & _NETWORK_MODULES and not _calls_helper(tree):
            found.append(path.name)
    return found


def test_the_scanned_package_holds_every_tool_the_agent_registers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[object] = []
    monkeypatch.setattr(
        agent_factory, "create_main_agent", lambda settings, tools: registered.extend(tools)
    )
    agent_factory.build_agent(Settings())
    assert {t.name for t in registered} == set(tools_package.__all__)  # type: ignore[attr-defined]
    for tool in registered:
        func = getattr(tool, "func", None) or tool.coroutine
        assert _TOOLS_DIR in Path(func.__code__.co_filename).parents


def test_no_tool_module_uses_the_network_without_the_ssrf_helper() -> None:
    assert _violations(_TOOLS_DIR) == []


def test_the_scan_flags_a_tool_that_fetches_without_the_helper(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import httpx\n\ndef fetch(u):\n    return httpx.get(u)\n")
    (tmp_path / "good.py").write_text(
        "import httpx\nfrom neuron_agent.security.input_policy import validate_safe_url\n\n"
        "def fetch(u):\n    return httpx.get(validate_safe_url(u))\n"
    )
    assert _violations(tmp_path) == ["bad.py"]


@pytest.mark.parametrize("tool", ["calculator", "utc_now"])
def test_registered_tools_take_no_url_argument(tool: str) -> None:
    schema = getattr(tools_package, tool).args
    assert not [name for name in schema if "url" in name.lower() or "uri" in name.lower()]
