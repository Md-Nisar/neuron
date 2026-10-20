"""No tool reaches the network except through the SSRF helper (ADR 0008 decision 12)."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import pytest

import neuron_agent.tools as tools_package
from neuron_agent.agents import factory as agent_factory
from neuron_agent.config.settings import Settings

_TOOLS_DIR = Path(tools_package.__file__).parent
_SRC_ROOT = _TOOLS_DIR.parent.parent
_PACKAGE = "neuron_agent"
# A tripwire, not a proof: a tool that imports any of these, directly or through
# a package module it imports, must call the SSRF helper.
_NETWORK_MODULES = {
    "httpx", "httpcore", "requests", "aiohttp", "urllib3", "urllib", "http", "socket", "ssl",
    "socketserver", "selectors", "asyncio", "ftplib", "smtplib", "imaplib", "poplib", "nntplib",
    "telnetlib", "xmlrpc", "websockets", "websocket", "grpc", "paramiko", "asyncssh", "pycurl",
    "niquests", "anyio", "trio", "webbrowser", "boto3", "botocore", "playwright", "selenium",
    "openai", "anthropic", "mcp", "langchain_community", "langchain_openai",
    "subprocess", "multiprocessing", "pty", "pexpect", "ctypes", "sh", "plumbum",
}  # fmt: skip
_PROCESS_OS_CALLS = {
    "system",
    "popen",
    "startfile",
    "fork",
    "forkpty",
    "posix_spawn",
    "posix_spawnp",
}
_HELPER = "validate_safe_url"
_HELPER_FILE = ("security", "input_policy.py")
_URL_WORDS = ("url", "uri", "href", "link", "endpoint", "host")


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


def _is_process_call(name: str) -> bool:
    return name in _PROCESS_OS_CALLS or name.startswith(("exec", "spawn"))


def _unfollowable_use(tree: ast.AST) -> bool:
    """Dynamic imports (which a static scan cannot follow) and process-starting os calls."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__import__":
            return True
        if isinstance(node, ast.Attribute) and node.attr in {"__import__", "import_module"}:
            return True
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "importlib" for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "importlib":
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            if any(_is_process_call(a.name) for a in node.names):
                return True
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and _is_process_call(node.attr)
        ):
            return True
    return False


def _module_name(path: Path, src_root: Path) -> list[str]:
    parts = list(path.relative_to(src_root).with_suffix("").parts)
    return parts[:-1] if parts[-1] == "__init__" else parts


def _local_imports(tree: ast.AST, path: Path, src_root: Path, package: str) -> set[Path]:
    """Files of package modules this file imports, relative imports included."""
    current = _module_name(path, src_root)
    base = current if path.name == "__init__.py" else current[:-1]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                prefix = base[: len(base) - node.level + 1]
                module = ".".join([*prefix, module] if module else prefix)
            names.add(module)
            names |= {f"{module}.{a.name}" for a in node.names}
    files: set[Path] = set()
    for name in names:
        if name == package or name.startswith(f"{package}."):
            stem = src_root.joinpath(*name.split("."))
            files |= {f for f in (stem.with_suffix(".py"), stem / "__init__.py") if f.is_file()}
    return files


def _closure(path: Path, src_root: Path, package: str) -> dict[Path, ast.AST]:
    """The file plus every package module it reaches; the helper's own module is not followed."""
    helper_file = src_root.joinpath(package, *_HELPER_FILE)
    trees: dict[Path, ast.AST] = {}
    pending = [path]
    while pending:
        current = pending.pop()
        if current in trees or current == helper_file:
            continue
        trees[current] = ast.parse(current.read_text())
        pending += _local_imports(trees[current], current, src_root, package)
    return trees


def _violations(directory: Path, src_root: Path = _SRC_ROOT, package: str = _PACKAGE) -> list[str]:
    found: set[str] = set()
    for tool_file in sorted(directory.rglob("*.py")):
        for path, tree in _closure(tool_file, src_root, package).items():
            label = tool_file.name if path == tool_file else f"{tool_file.name} via {path.name}"
            if _unfollowable_use(tree) or (
                _imported_roots(tree) & _NETWORK_MODULES and not _calls_helper(tree)
            ):
                found.add(label)
    return sorted(found)


def _registered_tools() -> list[object]:
    registered: list[object] = []
    with mock.patch.object(
        agent_factory, "create_main_agent", lambda settings, tools: registered.extend(tools)
    ):
        agent_factory.build_agent(Settings())
    return registered


_REGISTERED = _registered_tools()


def test_the_scanned_package_holds_every_tool_the_agent_registers() -> None:
    assert {t.name for t in _REGISTERED} == set(tools_package.__all__)  # type: ignore[attr-defined]
    for tool in _REGISTERED:
        func = getattr(tool, "func", None) or tool.coroutine  # type: ignore[attr-defined]
        assert _TOOLS_DIR in Path(func.__code__.co_filename).parents


def test_no_tool_module_uses_the_network_without_the_ssrf_helper() -> None:
    assert _violations(_TOOLS_DIR) == []


_FETCH = "import httpx\n\ndef fetch(u):\n    return httpx.get(u)\n"
_GUARDED = (
    "import httpx\nfrom fake.security.input_policy import validate_safe_url\n\n"
    "def fetch(u):\n    return httpx.get(validate_safe_url(u))\n"
)
_HELPER_STUB = "from urllib.parse import urlparse\n\ndef validate_safe_url(u):\n    return u\n"
_SCAN_CASES = [
    ({"tools/bad.py": _FETCH, "tools/good.py": _GUARDED}, ["bad.py"]),
    ({"tools/good.py": _GUARDED}, []),
    ({"tools/t.py": "import socket\n"}, ["t.py"]),
    ({"tools/t.py": "import ssl\n"}, ["t.py"]),
    ({"tools/t.py": "import subprocess\n"}, ["t.py"]),
    ({"tools/t.py": "import multiprocessing\n"}, ["t.py"]),
    ({"tools/t.py": "import asyncio\n"}, ["t.py"]),
    ({"tools/t.py": "import urllib.request\n"}, ["t.py"]),
    ({"tools/t.py": "from http import client\n"}, ["t.py"]),
    ({"tools/t.py": "import importlib\n"}, ["t.py"]),
    ({"tools/t.py": "from importlib import import_module\n"}, ["t.py"]),
    ({"tools/t.py": "def f(n):\n    return __import__(n)\n"}, ["t.py"]),
    ({"tools/t.py": "import os\n\ndef f():\n    os.system('id')\n"}, ["t.py"]),
    ({"tools/t.py": "import os\n\ndef f():\n    os.execv('/bin/sh', [])\n"}, ["t.py"]),
    ({"tools/t.py": "from os import popen\n"}, ["t.py"]),
    ({"tools/t.py": "import os\n\ndef f():\n    return os.getcwd()\n"}, []),
    # A wrapper outside tools/ that fetches, reached by absolute, relative or chained imports.
    (
        {"tools/t.py": "from fake.clients import web\n", "clients/web.py": _FETCH},
        ["t.py via web.py"],
    ),
    ({"tools/t.py": "from ..clients import web\n", "clients/web.py": _FETCH}, ["t.py via web.py"]),
    (
        {
            "tools/t.py": "import fake.clients.mid\n",
            "clients/mid.py": "from . import web\n",
            "clients/web.py": _FETCH,
        },
        ["t.py via web.py"],
    ),
    ({"tools/t.py": "from fake.clients import web\n", "clients/web.py": _GUARDED}, []),
]


@pytest.mark.parametrize(("files", "expected"), _SCAN_CASES)
def test_the_scan_flags_egress_paths_a_tool_could_use(
    tmp_path: Path, files: dict[str, str], expected: list[str]
) -> None:
    files = {"security/input_policy.py": _HELPER_STUB, **files}
    for name, text in files.items():
        target = tmp_path / "fake" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    for directory in [
        tmp_path / "fake",
        *(p for p in (tmp_path / "fake").rglob("*") if p.is_dir()),
    ]:
        (directory / "__init__.py").touch()
    assert _violations(tmp_path / "fake" / "tools", tmp_path, "fake") == expected


@pytest.mark.parametrize("tool", _REGISTERED, ids=lambda t: t.name)  # type: ignore[attr-defined]
def test_registered_tools_take_no_url_argument(tool: object) -> None:
    args = tool.args  # type: ignore[attr-defined]
    offenders = [
        name
        for name, spec in args.items()
        if any(word in name.lower() for word in _URL_WORDS)
        or spec.get("format") in {"uri", "url", "hostname"}
    ]
    assert not offenders, (
        f"tool {tool.name!r} takes URL-like argument(s) {offenders}. A tool that accepts a "  # type: ignore[attr-defined]
        f"URL must call {_HELPER} (see SECURITY.md); extend this test deliberately."
    )
