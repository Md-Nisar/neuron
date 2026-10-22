from __future__ import annotations

import ast
from pathlib import Path

import neuron_agent

_SECURITY = Path(neuron_agent.__file__).parent / "security"


def test_security_never_imports_persistence() -> None:
    """`persistence/` may import `security/`, never the reverse (ADR 0008 decision 8)."""
    offenders: list[str] = []
    for path in sorted(_SECURITY.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            if any(".persistence" in f".{name}" for name in names):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
