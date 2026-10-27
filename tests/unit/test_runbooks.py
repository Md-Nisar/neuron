# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The runbooks exist, name real commands and carry no secret (#154)."""

from __future__ import annotations

import re
from pathlib import Path

OPERATIONS = Path("OPERATIONS.md").read_text("utf-8")
CLI = Path("src/neuron_agent/persistence/cli.py").read_text("utf-8")

_RUNBOOKS = (
    "Deploy",
    "Rollback",
    "Migration failure",
    "Roles",
    "Rotation",
    "Backups and restore",
    "Capacity",
    "Platform facts",
)


def test_every_required_runbook_has_a_heading() -> None:
    headings = set(re.findall(r"^### (.+)$", OPERATIONS, flags=re.MULTILINE))
    assert set(_RUNBOOKS) <= headings
    assert "## Runbooks" in OPERATIONS


def test_the_cli_commands_in_the_docs_exist() -> None:
    for subcommand in set(re.findall(r"persistence\.cli (\w+)", OPERATIONS)):
        assert f'"{subcommand}"' in CLI, subcommand
    for flag in set(re.findall(r"cli setup (--[\w-]+)", OPERATIONS)):
        assert f'"{flag}"' in CLI, flag


def test_the_runbooks_state_that_nothing_was_rehearsed_and_render_facts_are_assumed() -> None:
    section = OPERATIONS[OPERATIONS.index("## Runbooks") :]
    assert "unrehearsed" in section and "assumption" in section
    assert "has not been rehearsed" in section  # the restore drill


def test_the_runbooks_hold_no_real_dsn_password_or_hook_url() -> None:
    section = OPERATIONS[OPERATIONS.index("## Runbooks") :]
    assert not re.search(r"postgres(ql)?://[^\s<]*:[^\s<@]+@", section)
    assert "api.render.com/deploy" not in section
    assert not re.search(r"sk-[A-Za-z0-9]{10,}", section)


def test_rotation_names_every_secret_with_a_maximum_age() -> None:
    rotation = OPERATIONS[OPERATIONS.index("### Rotation") : OPERATIONS.index("### Backups")]
    for secret in (
        "OPENAI_API_KEY",
        "Database role passwords",
        "IdP signing keys",
        "Smoke-test credential",
        "Deploy hooks",
        "APP_IDENTITY_HASH_KEY",
    ):
        assert secret in rotation, secret
    assert rotation.count("days") >= 4
    assert "scale the web service to zero" in rotation.lower()
