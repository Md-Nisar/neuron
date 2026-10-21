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


def test_dependency_layer_precedes_source_and_syncs_use_the_lockfile_only() -> None:
    syncs = [
        line.removeprefix("RUN ")
        for line in DOCKERFILE.read_text("utf-8").splitlines()
        if line.startswith("RUN uv sync")
    ]
    assert syncs == [
        "uv sync --frozen --no-dev --no-install-project",
        "uv sync --frozen --no-dev --no-editable",
    ]
