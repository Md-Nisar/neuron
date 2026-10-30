# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Layout of the built container image (issue #134, ADR 0008 decision 2).

The image is built once by the `docker-build` workflow (`docker build -t neuron-test .`) and
reused here; set `NEURON_TEST_IMAGE` to test another tag. The tests skip when the Docker CLI,
the daemon or the image is unavailable. Containers start with test settings only: no secret.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404
import time
import uuid
from collections.abc import Iterator

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.docker]

IMAGE = os.environ.get("NEURON_TEST_IMAGE", "neuron-test")
EXPECTED_CMD = ["neuron-api"]
EXPECTED_HEALTHCHECK_COMMAND = (
    'python -c "from neuron_agent.config.settings import Settings; import urllib.request; '
    "urllib.request.urlopen('http://127.0.0.1:%d/health/live' % Settings().port, "
    'timeout=2).read()"'
)
SECOND = 1_000_000_000  # Docker reports healthcheck durations in nanoseconds.


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.fixture(scope="module", autouse=True)
def _image_available() -> None:
    try:
        inspected = _docker("image", "inspect", IMAGE)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("docker is not available")
    if inspected.returncode != 0:
        pytest.skip(f"image {IMAGE!r} is not available (no daemon, or not built)")


def _run(*command: str) -> str:
    result = _docker("run", "--rm", "--entrypoint", command[0], IMAGE, *command[1:])
    assert result.returncode == 0, result.stderr
    return result.stdout


def _config() -> dict[str, object]:
    inspected = json.loads(_docker("image", "inspect", IMAGE).stdout)[0]
    config: dict[str, object] = inspected["Config"]
    return config


def test_only_the_virtualenv_is_in_app() -> None:
    assert _run("ls", "-A", "/app").split() == [".venv"]
    for path in ("/app/tests", "/app/evals", "/app/.git", "/app/src", "/app/pyproject.toml"):
        assert (
            _docker("run", "--rm", "--entrypoint", "test", IMAGE, "!", "-e", path).returncode == 0
        )


def test_no_pip_or_setuptools_in_the_runtime_image() -> None:
    # The base image's pip and setuptools are removed; the app runs from /app/.venv (#140).
    for module in ("pip", "setuptools", "pkg_resources"):
        result = _docker(
            "run", "--rm", "--entrypoint", "/usr/local/bin/python", IMAGE, "-c", f"import {module}"
        )
        assert result.returncode != 0, module
    assert _docker("run", "--rm", "--entrypoint", "which", IMAGE, "pip").returncode != 0


def test_no_secret_files_under_app() -> None:
    assert _run("find", "/app", "-name", ".env*").strip() == ""
    # certifi ships cacert.pem inside site-packages, so key material is checked outside it.
    found = _run(
        "find", "/app", "-path", "/app/.venv/lib", "-prune", "-o",
        "(", "-name", "*.pem", "-o", "-name", "*.key", ")", "-print",
    )  # fmt: skip
    assert found.strip() == ""


def test_package_is_installed_not_editable_and_the_prompt_loads() -> None:
    script = (
        "import neuron_agent, neuron_agent.api.main;"
        "from neuron_agent.prompts.loader import load_prompt;"
        "assert '/app/.venv/lib/' in neuron_agent.__file__;"
        "assert 'site-packages' in neuron_agent.__file__;"
        "assert load_prompt('system/main.md');"
        "print('ok')"
    )
    assert _run("python", "-c", script).strip() == "ok"


def test_user_is_a_numeric_non_root_uid() -> None:
    assert _config()["User"] == "10001:10001"
    assert _run("id", "-u").strip() == "10001"
    assert _run("id", "-g").strip() == "10001"


def test_cmd_and_healthcheck_are_exactly_the_expected_ones() -> None:
    config = _config()
    assert config["Cmd"] == EXPECTED_CMD
    assert not config.get("Entrypoint")
    assert config["Healthcheck"] == {
        "Test": ["CMD-SHELL", EXPECTED_HEALTHCHECK_COMMAND],
        "Interval": 30 * SECOND,
        "Timeout": 3 * SECOND,
        "StartPeriod": 10 * SECOND,
        "Retries": 3,
    }


def test_image_binds_publicly_but_refuses_to_start_without_an_explicit_app_env() -> None:
    env = _config()["Env"]
    assert isinstance(env, list)
    assert {"APP_HOST=0.0.0.0", "APP_PORT=8000"} <= set(env)
    # No APP_ENV: it would default to development without authentication on 0.0.0.0.
    result = _docker("run", "--rm", IMAGE, timeout=120)
    assert result.returncode != 0
    assert "APP_ENV" in result.stderr


def test_oci_labels_are_present() -> None:
    labels = _config()["Labels"]
    assert isinstance(labels, dict)
    assert labels["org.opencontainers.image.source"] == "https://github.com/Md-Nisar/neuron"
    assert labels["org.opencontainers.image.revision"]
    assert labels["org.opencontainers.image.version"]


@pytest.fixture
def container() -> Iterator[str]:
    name = f"neuron-layout-{uuid.uuid4().hex[:8]}"
    started = _docker(
        "run", "-d", "--name", name,
        "-e", "APP_ENV=test", "-e", "APP_HOST=127.0.0.1",
        "-e", "APP_OTEL_ENABLED=false", "-e", "APP_ENABLE_LANGSMITH=false",
        IMAGE,
    )  # fmt: skip
    assert started.returncode == 0, started.stderr
    try:
        yield name
    finally:
        _docker("rm", "-f", name)


def test_health_live_answers_from_inside_a_container_with_test_settings(container: str) -> None:
    deadline = time.monotonic() + 60
    last = ""
    while time.monotonic() < deadline:
        # The HEALTHCHECK command itself, run the way Docker runs it (CMD-SHELL).
        result = _docker("exec", container, "sh", "-c", EXPECTED_HEALTHCHECK_COMMAND)
        if result.returncode == 0:
            return
        last = result.stderr
        time.sleep(1)
    logs = _docker("logs", container)
    pytest.fail(f"/health/live never answered: {last}\n{logs.stdout}{logs.stderr}")
