"""`DoclingServeParser` against a real docling-serve, and its network (RAG-02.02 AC1, AC5).

Opt-in, excluded from `make test` by the `integration` marker. The image is the one pinned in
`docker-compose.reference.yml`:

    docker run --rm -p 127.0.0.1:5001:5001 <docling image from the reference stack>
    APP_TEST_DOCLING_URL=http://127.0.0.1:5001 uv run python -m pytest -m integration \\
        tests/integration/test_docling_serve.py

The parse test downloads `nist-cswp-29` from its source and checks its SHA-256; the container
above has network access, so give it only this public file. The egress test needs Docker and the
image, and runs the parser on the reference stack's `parser` network in its own compose project,
so a running reference stack is left alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess  # noqa: S404
import urllib.request
from pathlib import Path

import pytest
import yaml

from neuron_agent.knowledge.docling_serve import DoclingServeParser
from neuron_agent.knowledge.parsing import PDF, Limits

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_CASES = json.loads((_ROOT / "tests/fixtures/knowledge_cases.json").read_text("utf-8"))
_COMPOSE = _ROOT / "docker-compose.reference.yml"
_URL = os.environ.get("APP_TEST_DOCLING_URL")


def _norm(text: str) -> str:
    text = text.replace("­", "").replace("ﬁ", "fi").replace("’", "'")
    return re.sub(r"\s+", " ", text).lower().strip()


def _download(document: str) -> bytes:
    (entry,) = [d for d in _CASES["documents"] if d["id"] == document]
    url = entry["source"]["url"]
    assert url.startswith("https://")
    # nvlpubs.nist.gov refuses urllib's default User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "neuron-tests"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - https, fixed corpus
        data: bytes = response.read()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"], "the source file changed"
    return data


@pytest.mark.anyio
@pytest.mark.skipif(not _URL, reason="set APP_TEST_DOCLING_URL to a running docling-serve")
async def test_docling_serve_keeps_a_corpus_pdfs_pages_and_headings() -> None:
    assert _URL is not None
    parser = DoclingServeParser(_URL, timeout_seconds=600, max_response_bytes=64_000_000)
    parsed = await parser.parse(_download("nist-cswp-29"), PDF, Limits(50_000_000, 2_000, 50_000))
    assert parsed.page_count == 32
    pages: dict[int | None, str] = {}
    for block in parsed.blocks:
        pages[block.page] = pages.get(block.page, "") + " " + _norm(block.text)
    for case in _CASES["cases"]:
        for source in case.get("expected_sources", []):
            if source["document"] == "nist-cswp-29":
                evidence = _norm(case["evidence"])
                assert any(evidence in pages.get(page, "") for page in source["pages"]), case["id"]
    assert len([block for block in parsed.blocks if block.kind == "heading"]) >= 20


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env={**os.environ, "NEURON_IMAGE": "unused"},
    )


@pytest.mark.docker
def test_the_parser_cannot_connect_out() -> None:
    image = yaml.safe_load(_COMPOSE.read_text("utf-8"))["services"]["docling"]["image"]
    try:
        available = _docker("image", "inspect", image).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        available = False
    if not available:
        pytest.skip("docker or the docling-serve image is not available")
    # Prints `blocked` only if the connection fails, so a missing interpreter cannot pass.
    probe = (
        "import socket\n"
        "try:\n    socket.create_connection(('1.1.1.1', 443), timeout=5)\n"
        "except OSError:\n    print('blocked')"
    )
    compose = ["compose", "-p", "neuron-egress-test", "-f", str(_COMPOSE), "--profile", "knowledge"]
    try:
        result = _docker(
            *compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "docling", "-c", probe
        )
    finally:
        _docker(*compose, "down")
    assert result.stdout.strip().splitlines()[-1:] == ["blocked"], result.stderr
