from __future__ import annotations

import ast
from pathlib import Path

import neuron_agent

_SECURITY = Path(neuron_agent.__file__).parent / "security"


def _security_imports_of(package: str) -> list[str]:
    """Every import in `security/` that names `package`, at any depth (inside functions too)."""
    offenders: list[str] = []
    for path in sorted(_SECURITY.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            if any(f".{package}" in f".{name}" for name in names):
                offenders.append(f"{path.name}:{node.lineno}")
    return offenders


def test_security_never_imports_persistence() -> None:
    """`persistence/` may import `security/`, never the reverse (ADR 0008 decision 8)."""
    assert _security_imports_of("persistence") == []


def test_security_never_imports_api() -> None:
    """`api/` wires `security/` up and injects what it needs (#148); no import points back."""
    assert _security_imports_of("api") == []
