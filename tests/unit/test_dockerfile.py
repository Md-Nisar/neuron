# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The builder and runtime stages must share a Python minor version and a Debian release."""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path("Dockerfile")
_DEBIAN = ("bookworm", "trixie", "bullseye", "forky")


def _from_images(text: str) -> list[str]:
    return [
        line.split()[1] for line in text.splitlines() if line.strip().upper().startswith("FROM ")
    ]


def _python_version(image: str) -> str | None:
    match = re.search(r"python:?-?(\d+\.\d+)", image)
    return match.group(1) if match else None


def _debian(image: str) -> str | None:
    return next((name for name in _DEBIAN if name in image), None)


def _check(text: str) -> list[str]:
    images = _from_images(text)
    if len(images) != 2:
        return [f"expected 2 stages, found {len(images)}"]
    builder, runtime = images
    problems = []
    if _python_version(builder) is None or _python_version(builder) != _python_version(runtime):
        problems.append(f"python differs: {builder} vs {runtime}")
    if _debian(builder) is None or _debian(builder) != _debian(runtime):
        problems.append(f"debian release differs: {builder} vs {runtime}")
    return problems


def test_dockerfile_stages_share_python_minor_and_debian_release() -> None:
    assert _check(DOCKERFILE.read_text("utf-8")) == []


def test_the_check_rejects_a_python_or_debian_mismatch() -> None:
    uv = "FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim AS builder\n"
    assert _check(uv + "FROM python:3.13-slim-trixie\n") == []
    assert _check(uv + "FROM python:3.14-slim\n")
    assert _check(uv + "FROM python:3.14-slim-trixie\n")
    assert _check(uv + "FROM python:3.13-slim-bookworm\n")
    assert _check(uv + "FROM python:3.13-slim\n")


def test_both_bases_are_pinned_by_digest_with_the_tag_kept() -> None:
    text = DOCKERFILE.read_text("utf-8")
    for image in _from_images(text):
        assert re.fullmatch(r"[^:@\s]+(:[^@\s]+)?:[^@\s]+@sha256:[0-9a-f]{64}", image), image
        assert image.split("@")[0] in text.replace(image, "")  # the tag also sits in a comment


def test_the_check_parses_tag_plus_digest_forms() -> None:
    digest = "@sha256:" + "a" * 64
    uv = f"FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim{digest} AS builder\n"
    assert _check(uv + f"FROM python:3.13-slim-trixie{digest}\n") == []
    assert _check(uv + f"FROM python:3.14-slim-trixie{digest}\n")
    assert _check(uv + f"FROM python:3.13-slim-bookworm{digest}\n")


def test_runtime_user_is_numeric_and_only_the_venv_is_copied() -> None:
    lines = DOCKERFILE.read_text("utf-8").splitlines()
    assert "USER 10001:10001" in lines
    assert "COPY --from=builder /app/.venv /app/.venv" in lines
    assert [line for line in lines if line.startswith("COPY --from=")] == [
        "COPY --from=builder /app/.venv /app/.venv"
    ]
    assert not any(line.startswith(("COPY . ", "ADD ")) for line in lines)


def test_oci_labels_and_build_args_carry_no_secrets() -> None:
    text = DOCKERFILE.read_text("utf-8")
    args = re.findall(r"^ARG (\w+)", text, re.MULTILINE)
    assert args == ["GIT_SHA", "VERSION"]
    for label in ("source", "revision", "version"):
        assert f"org.opencontainers.image.{label}=" in text


def test_dockerignore_is_an_allowlist_covering_what_the_build_copies() -> None:
    rules = [
        line.strip()
        for line in Path(".dockerignore").read_text("utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert rules[0] == "*"
    allowed = {rule[1:].rstrip("/") for rule in rules if rule.startswith("!")}
    copied = set()
    for line in DOCKERFILE.read_text("utf-8").splitlines():
        if line.startswith("COPY ") and "--from" not in line:
            sources = line.split()[1:-1]
            copied |= {source.removesuffix("/") for source in sources}
    assert copied <= allowed, copied - allowed
    assert allowed == {"pyproject.toml", "uv.lock", "README.md", "LICENSE", "NOTICE", "src"}


def test_dependency_layer_precedes_source_and_syncs_use_the_lockfile_only() -> None:
    syncs = [
        line.removeprefix("RUN ")
        for line in DOCKERFILE.read_text("utf-8").splitlines()
        if line.startswith("RUN uv sync")
    ]
    assert syncs == [
        "uv sync --locked --no-dev --no-install-project",
        "uv sync --locked --no-dev --no-editable",
    ]
