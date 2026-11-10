"""The Knowledge Engine module boundaries that AGENTS.md and CLAUDE.md state (RAG-08.04 AC2)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "neuron_agent"
# Layers `knowledge/` must not depend on: it sits below the request flow, not inside it.
_FORBIDDEN = {"api", "services", "graphs", "agents", "models"}
# The only layers that may import `knowledge/`, and the modules each may use.
_ALLOWED_IMPORTERS = {"api": None, "services": None, "graphs": {"neuron_agent.knowledge.citations"}}


def _imports(path: Path) -> set[str]:
    """Absolute `neuron_agent...` modules a file imports (a `from x import y` may name module y)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return {name for name in names if name.startswith("neuron_agent.")}


def _layer(module: str) -> str:
    return module.split(".")[1]


def test_knowledge_never_imports_the_layers_above_it() -> None:
    found = {
        f"{path.relative_to(PACKAGE)} imports {module}"
        for path in (PACKAGE / "knowledge").glob("*.py")
        for module in _imports(path)
        if _layer(module) in _FORBIDDEN
    }
    assert not found, sorted(found)


def test_only_api_services_and_graphs_import_knowledge() -> None:
    found = set()
    for path in PACKAGE.rglob("*.py"):
        layer = path.relative_to(PACKAGE).parts[0]
        if layer == "knowledge":
            continue
        for module in _imports(path):
            if not module.startswith("neuron_agent.knowledge"):
                continue
            allowed = _ALLOWED_IMPORTERS.get(layer, set())
            # `from neuron_agent.knowledge import citations` names the package and the module.
            if allowed is None or module == "neuron_agent.knowledge" or module in allowed:
                continue
            found.add(f"{path.relative_to(PACKAGE)} imports {module}")
    assert not found, sorted(found)


def test_agents_md_and_claude_md_state_the_boundaries() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Knowledge Engine Boundaries" in agents
    assert "- `knowledge/` — the Knowledge Engine (ADR 0014)" in claude
    for text in (agents, claude):
        assert "tests/unit/test_knowledge_boundaries.py" in text
