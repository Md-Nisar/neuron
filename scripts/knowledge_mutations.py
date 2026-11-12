# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Mutation check of the knowledge security suite (RAG-08.02 AC2, #503).

For each of the twelve cases in `tests/security/test_knowledge_security_suite.py`, remove a
control that case relies on in a copy of `src/neuron_agent` (one mutant per control, several per
case where the case has several), run the case's tests against the copy, and require at least one
to fail on an assertion. A mutant whose tests all pass, or are all skipped (no
`APP_TEST_POSTGRES_DSN` for a Postgres case), fails the check.

    uv run python scripts/knowledge_mutations.py            # every case; needs Postgres
    uv run python scripts/knowledge_mutations.py --case "Erase everything"
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess  # noqa: S404 - runs pytest on our own tests
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree  # noqa: S405 - parses our own pytest output

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "neuron_agent"


@dataclass(frozen=True)
class Edit:
    path: str  # relative to src/neuron_agent
    old: str  # must occur exactly once
    new: str


@dataclass(frozen=True)
class Mutant:
    """One way to break a case: every edit is applied together, so a control kept in two layers
    (an owner filter in SQL and in `allowed_kbs`, say) is removed from both."""

    case: str
    name: str
    edits: tuple[Edit, ...]


_SERVICE, _AUTHZ = "knowledge/service.py", "knowledge/authorization.py"
# Any user's grants count as the caller's (the cast keeps the parameter typed for Postgres).
_ANY_OWNER = Edit(
    _AUTHZ, "g.subject = %(owner)s AND b.owner_key = %(owner)s", "%(owner)s::text IS NOT NULL"
)
_PARSING, _MAIN = "knowledge/parsing.py", "api/main.py"
_HIDDEN, _BOMB = "Instructions hidden in a document", "Zip bomb, page bomb, encrypted or macro file"

MUTANTS = [
    Mutant(
        "Foreign kb_id or doc_id",
        "rename ignores the owner",
        (Edit(_SERVICE, "_require(allowed, kb_id, allowed.admin)", "pass"),),
    ),
    Mutant(
        "Foreign kb_id or doc_id",
        "documents of any owner",
        (_ANY_OWNER,),
    ),
    Mutant(
        "Same text in two users' bases",
        "the search ignores the owner",
        (_ANY_OWNER,),
    ),
    Mutant(
        "Access revoked while a citation is open",
        "grants not read",
        (
            Edit(
                _AUTHZ,
                '"SELECT g.kb_id, g.access, g.subject_type FROM knowledge.grants g"\n'
                '    " JOIN knowledge.bases b USING (kb_id) WHERE b.deleted_at IS NULL AND ("\n'
                "    \"(g.subject_type = 'owner' AND g.subject = %(owner)s AND",
                "\"SELECT b.kb_id, 'admin' AS access, 'owner' AS subject_type\"\n"
                '    " FROM knowledge.bases b WHERE b.deleted_at IS NULL AND ("\n'
                '    "(%(owner)s::text IS NOT NULL AND',
            ),
            Edit(
                _AUTHZ,
                "\" OR (g.subject_type = 'role' AND g.subject = ANY(%(roles)s::text[])))\"",
                '" OR %(roles)s::text[] IS NULL)"',
            ),
        ),
    ),
    Mutant(
        "Delete during purge",
        "listed while deleting",
        (
            Edit(
                _SERVICE,
                "\" AND d.deleted_at IS NULL AND d.status <> 'deleting'\"\n)",
                '" AND true"\n)',
            ),
        ),
    ),
    Mutant(
        "Delete during purge",
        "chunk readable while deleting",
        (
            Edit(
                _SERVICE,
                "\" AND d.deleted_at IS NULL AND d.status = 'ready' AND d.doc_id = %(doc)s\"",
                '" AND d.doc_id = %(doc)s"',
            ),
        ),
    ),
    Mutant(
        _HIDDEN,
        "forget needs no approval",
        (
            Edit(
                "memory/tools.py",
                'ToolSpec(_report_errors(forget), MEMORY_TOOL_SCOPES["forget"], "mutating")',
                'ToolSpec(_report_errors(forget), MEMORY_TOOL_SCOPES["forget"], "read")',
            ),
        ),
    ),
    Mutant(
        _HIDDEN,
        "remember takes any text",
        (
            Edit(
                "memory/tools.py",
                "        if _words(text) not in _user_words(runtime.state):\n",
                "        if False:\n",
            ),
        ),
    ),
    Mutant(
        _HIDDEN,
        "framing keeps <",
        (Edit("tools/framing.py", '.replace("<", chr(92) + "u003c")', ""),),
    ),
    Mutant(
        "Fake or planted cite_id",
        "an unknown id resolves",
        (
            Edit(
                "knowledge/citations.py",
                "ref = known.get(cite_id)\n",
                "ref = known.get(cite_id) or next(iter(known.values()), None)\n",
            ),
        ),
    ),
    Mutant(
        "Exfiltration to MCP after a search",
        "knowledge tools do not taint",
        (Edit("knowledge/tools.py", '"read", taints_run=True)', '"read", taints_run=False)'),),
    ),
    Mutant(
        "Worker killed during ingestion",
        "stalled jobs never retried",
        (Edit("knowledge/worker.py", "for job in stalled:", "for job in stalled[:0]:"),),
    ),
    Mutant(
        "HTML or SVG download",
        "inline",
        (Edit(_MAIN, 'return f"attachment; filename=', 'return f"inline; filename='),),
    ),
    Mutant(
        "HTML or SVG download",
        "no nosniff",
        (
            Edit(_MAIN, ', "X-Content-Type-Options": "nosniff"}', "}"),
            Edit(_MAIN, 'response.headers["X-Content-Type-Options"] = "nosniff"', "pass"),
        ),
    ),
    Mutant(
        _BOMB,
        "no total inflate check",
        (
            Edit(
                _PARSING,
                "inflated > _MAX_COMPRESSION_RATIO * size\n"
                "        or inflated > _MAX_INFLATE_FACTOR * limits.max_bytes",
                "False",
            ),
        ),
    ),
    Mutant(
        _BOMB,
        "no page cap",
        (Edit(_PARSING, "if max(page_count, len(pages)) > limits.max_pages:", "if False:"),),
    ),
    Mutant(
        _BOMB,
        "encrypted PDF accepted",
        (Edit(_PARSING, "if _ENCRYPT.search(data):", "if False:"),),
    ),
    Mutant(
        "Erase everything",
        "complete before the purge",
        (
            Edit(
                _SERVICE,
                'purge_pending=stored is not None and bool(stored["stored"]),',
                "purge_pending=False,",
            ),
        ),
    ),
    Mutant(
        "Hosted provider under a self-hosted policy",
        "embedding call not checked",
        (
            Edit(
                "knowledge/providers.py",
                'raise EmbeddingError("processing_locality_forbidden")',
                "return",
            ),
        ),
    ),
    Mutant(
        "Hosted provider under a self-hosted policy",
        "start-up not checked",
        (
            Edit(
                "config/settings.py",
                'self.knowledge_processing_policy == "self_hosted_only"\n'
                '            and self.knowledge_embedding_locality_effective == "hosted"',
                "False",
            ),
        ),
    ),
]


def mutate(target: Path, mutant: Mutant) -> None:
    """Apply `mutant`'s edits to the package copy at `target`."""
    for edit in mutant.edits:
        path = target / edit.path
        source = path.read_text(encoding="utf-8")
        if source.count(edit.old) != 1:
            raise SystemExit(f"{mutant.name}: the mutated text is not in {edit.path} exactly once")
        path.write_text(source.replace(edit.old, edit.new), encoding="utf-8")


# A test that fails because the mutant broke the code itself (bad SQL, an import) proves nothing.
_NOT_A_CATCH = ("psycopg", "SyntaxError", "ImportError", "NameError", "IndentationError")


def outcome(report: Path) -> tuple[int, int, int]:
    """Tests run, tests failed on their assertions, and tests skipped, from a JUnit report.
    Errors (fixtures, collection) and failures from broken code do not count as caught."""
    root = ElementTree.parse(report).getroot()  # noqa: S314
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    failed = sum(
        1
        for failure in root.iter("failure")
        if not any(m in (failure.get("message") or "") for m in _NOT_A_CATCH)
    )
    return total, failed, skipped


def run(mutant: Mutant, nodes: list[str]) -> str | None:
    """Return why the mutant survived, or None when a test caught it."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "src"
        shutil.copytree(
            PACKAGE, copy / "neuron_agent", ignore=shutil.ignore_patterns("__pycache__")
        )
        mutate(copy / "neuron_agent", mutant)
        # PYTHONPATH comes before the editable install's .pth entry, so the copy is imported.
        env = {**os.environ, "PYTHONPATH": str(copy), "PYTHONDONTWRITEBYTECODE": "1"}
        where = subprocess.run(  # noqa: S603
            [sys.executable, "-c", "import neuron_agent; print(neuron_agent.__file__)"],
            env=env, capture_output=True, text=True, check=True, cwd=ROOT,
        ).stdout  # fmt: skip
        if not where.startswith(str(copy)):
            raise SystemExit(f"the mutated copy was not imported: {where}")
        report = Path(tmp) / "junit.xml"
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider",
             "-m", "integration or not integration", f"--junitxml={report}"],
            env=env, cwd=ROOT, capture_output=True, text=True, check=False, timeout=600,
        )  # fmt: skip
        total, failed, skipped = outcome(report)
    if failed:
        return None
    print(result.stdout[-3000:], file=sys.stderr)  # why it survived
    if total and skipped == total:
        return f"all {total} tests skipped (is APP_TEST_POSTGRES_DSN set?)"
    return f"{total - skipped} tests run, none failed on an assertion, {skipped} skipped"


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(ROOT))
    from tests.security.test_knowledge_security_suite import SUITE

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", action="append", help="run only this case (repeatable)")
    cases = parser.parse_args(argv).case or [m.case for m in MUTANTS]
    survived = 0
    for mutant in MUTANTS:
        if mutant.case not in cases:
            continue
        why = run(mutant, SUITE[mutant.case])
        label = f"{mutant.case} / {mutant.name}"
        print(f"{'survived' if why else 'caught':>8}  {label}" + (f": {why}" if why else ""))
        survived += why is not None
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
