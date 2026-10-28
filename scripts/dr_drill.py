# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Restore drill on the reference stack (ADR 0012 decision 8, #332). Local use only.

    NEURON_IMAGE=neuron:ref make reference-up
    NEURON_IMAGE=neuron:ref uv run python -m scripts.dr_drill

Follows OPERATIONS.md, "Backups and restore", on the reference stack's Postgres (WAL archiving
on): seed threads and memories, take a base backup, write more, record a point in time T, erase
one user's data after T, then restore to T into a *new* container, run `setup`, point a
throwaway API replica at it and run the smoke test, replay the erasure, check the `UNLOGGED`
rate-limit table came back empty, and delete everything the drill created. Prints the template
fields of the runbook, including RTO and RPO. Needs Docker and the running reference stack.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404  (fixed docker CLI calls; no shell, no user input)
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loadtest.identity import TokenSource, provision_users, username

COMPOSE = ["docker", "compose", "-f", "docker-compose.reference.yml"]
POSTGRES_IMAGE = "postgres:16"
API = "http://127.0.0.1:8101"
RESTORE = "neuron-dr-restore"
STAGING_API = "neuron-dr-staging"
RESTORE_API_PORT = 8199
NETWORK = "neuron_default"
MIGRATOR_PASSWORD = "migrator-local-only"  # noqa: S105  # nosec B105  (reference stack)
APP_PASSWORD = "app-local-only"  # noqa: S105  # nosec B105
ALICE, BOB = username(900), username(901)
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def run(*args: str, check: bool = True, quiet: bool = True) -> str:
    result = subprocess.run(  # noqa: S603  # nosec B603
        list(args), capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args[:4])}\n{result.stderr[-800:]}")
    if not quiet:
        print(result.stdout)
    return result.stdout.strip()


def container(service: str) -> str:
    return run(*COMPOSE, "ps", "-q", service)


def psql(target: str, sql: str, user: str = "neuron_owner") -> str:
    return run("docker", "exec", target, "psql", "-U", user, "-d", "neuron", "-tAc", sql)


def api(
    method: str, path: str, token: str, body: dict[str, Any] | None = None, base: str = API
) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(  # noqa: S310  # nosec B310  (http to loopback)
        base + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with _NO_PROXY.open(request, timeout=60) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def stream(token: str, message: str, base: str = API) -> dict[str, Any]:
    """Run one streamed turn and return its terminal event (final or approval_required)."""
    status, text = api("POST", "/v1/agent/stream", token, {"message": message}, base)
    if status != 200:
        raise SystemExit(f"stream failed: HTTP {status}")
    event, last = "", {}
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:") and event in {"final", "approval_required"}:
            last = {"event": event, **json.loads(line[5:])}
    return last


def seed(token: str, threads: int, memories: int) -> None:
    for index in range(threads):
        stream(token, f"hello {index}")
    for index in range(memories):
        paused = stream(token, f"remember: drill note {index}")
        path = f"/v1/threads/{paused['thread_id']}/approvals/{paused['approval']['approval_id']}"
        api("POST", path, token, {"decision": "approve"})


def thread_total(token: str, base: str = API) -> int:
    status, text = api("GET", "/v1/me/threads?limit=1", token, base=base)
    return int(json.loads(text)["total"]) if status == 200 else -1


def wait_for(description: str, check: Any, seconds: int = 120) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(1)
    raise SystemExit(f"timed out waiting for {description}")


def main() -> int:
    if not os.environ.get("NEURON_IMAGE"):
        print("set NEURON_IMAGE to the image under test", file=sys.stderr)
        return 2
    started_at = datetime.now(UTC)
    source = container("postgres")
    provision_users(902)
    alice, bob = TokenSource(ALICE), TokenSource(BOB)
    work = Path(tempfile.mkdtemp(prefix="neuron-dr-"))
    steps: dict[str, Any] = {}
    try:
        # 1. Seed, then take a base backup (pg_basebackup) while WAL archiving runs.
        seed(alice.get(), threads=3, memories=2)
        seed(bob.get(), threads=3, memories=0)
        before_backup = thread_total(alice.get()), thread_total(bob.get())
        psql(source, "SELECT pg_switch_wal()")
        run("docker", "exec", "-u", "postgres", source, "rm", "-rf", "/var/lib/postgresql/backup")
        run(
            "docker", "exec", "-u", "postgres", source, "pg_basebackup", "-D",
            "/var/lib/postgresql/backup", "-Fp", "-X", "none", "-c", "fast", "-U", "neuron_owner",
        )  # fmt: skip
        steps["backup_taken"] = datetime.now(UTC).isoformat()
        # 2. Write more, record the point in time T, then bob erases his data after T.
        seed(alice.get(), threads=2, memories=0)
        time.sleep(2)
        point_in_time = psql(source, "SELECT clock_timestamp()")
        newest_before_t = psql(source, "SELECT now()")
        time.sleep(2)
        status, erased = api("DELETE", "/v1/me/threads", bob.get())
        seed(alice.get(), threads=1, memories=0)
        rate_rows_source = int(psql(source, "SELECT count(*) FROM neuron_rate_buckets"))
        incident_at = datetime.now(UTC)
        psql(source, "SELECT pg_switch_wal()")
        time.sleep(3)  # let the archiver ship the last segment
        steps["erasure_after_T"] = {"http": status, "body": json.loads(erased)}
        after_incident = thread_total(alice.get()), thread_total(bob.get())

        # 3. Restore to T in a NEW container. RTO runs from here to a usable database.
        restore_started = time.monotonic()
        shutil.rmtree(work / "backup", ignore_errors=True)
        run("docker", "cp", f"{source}:/var/lib/postgresql/backup", str(work / "backup"))
        run("docker", "cp", f"{source}:/var/lib/postgresql/wal_archive", str(work / "archive"))
        (work / "backup" / "recovery.signal").write_text("", encoding="utf-8")
        run("chmod", "-R", "go-rwx", str(work / "backup"))
        run("chmod", "755", str(work / "archive"))
        run("docker", "rm", "-f", RESTORE, check=False)
        run(
            "docker", "run", "-d", "--name", RESTORE, "--network", NETWORK,
            "-v", f"{work / 'backup'}:/var/lib/postgresql/data",
            "-v", f"{work / 'archive'}:/archive:ro", POSTGRES_IMAGE,
            "postgres", "-c", "restore_command=cp /archive/%f %p",
            "-c", f"recovery_target_time={point_in_time}+00",
            "-c", "recovery_target_action=promote", "-c", "recovery_target_inclusive=true",
        )  # fmt: skip
        wait_for("the restored database", lambda: psql_ready(RESTORE))
        steps["restore_usable_seconds"] = round(time.monotonic() - restore_started, 1)

        # 4. Roles come with the cluster; run `setup` as the migrator, then a staging replica.
        env = reference_env()
        run(
            "docker", "run", "--rm", "--network", NETWORK, *env_args(env),
            "-e", f"APP_POSTGRES_MIGRATION_DSN=postgresql://neuron_migrator:{MIGRATOR_PASSWORD}"
            f"@{RESTORE}:5432/neuron?sslmode=disable",
            "-e", f"APP_POSTGRES_DSN=postgresql://neuron_app:{APP_PASSWORD}@{RESTORE}:5432/neuron"
            "?sslmode=disable",
            os.environ["NEURON_IMAGE"], "python", "-m", "neuron_agent.persistence.cli", "setup",
        )  # fmt: skip
        run("docker", "rm", "-f", STAGING_API, check=False)
        run(
            "docker", "run", "-d", "--name", STAGING_API, "--network", NETWORK,
            "-p", f"127.0.0.1:{RESTORE_API_PORT}:8000", *env_args(env),
            "-e", f"APP_POSTGRES_DSN=postgresql://neuron_app:{APP_PASSWORD}@{RESTORE}:5432/neuron"
            "?sslmode=disable",
            os.environ["NEURON_IMAGE"],
        )  # fmt: skip
        staging = f"http://127.0.0.1:{RESTORE_API_PORT}"
        wait_for("the staging replica", lambda: api("GET", "/health/ready", "x", base=staging)[0] == 200)
        smoke = subprocess.run(  # noqa: S603  # nosec B603
            [sys.executable, "scripts/smoke_test.py", staging],
            env={**os.environ, "SMOKE_TEST_TOKEN": alice.get()},
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        steps["smoke_test"] = (smoke.stdout + smoke.stderr).strip()

        # 5. Counts, the erasure replay, and the UNLOGGED table.
        restored_before_replay = thread_total(alice.get(), staging), thread_total(bob.get(), staging)
        rate_rows_restored = int(psql(RESTORE, "SELECT count(*) FROM neuron_rate_buckets"))
        replay_status, _ = api("DELETE", "/v1/me/threads", bob.get(), base=staging)
        restored_after_replay = thread_total(alice.get(), staging), thread_total(bob.get(), staging)
        newest_restored = psql(RESTORE, "SELECT max(updated_at) FROM neuron_thread_meta")
        newest_source = psql(source, "SELECT max(updated_at) FROM neuron_thread_meta")
        steps.update(
            threads_alice_bob_before_backup=before_backup,
            threads_alice_bob_at_incident=after_incident,
            threads_alice_bob_restored_before_replay=restored_before_replay,
            threads_alice_bob_restored_after_replay=restored_after_replay,
            erasure_replay_http=replay_status,
            rate_bucket_rows_source=rate_rows_source,
            rate_bucket_rows_restored=rate_rows_restored,
            newest_thread_restored=newest_restored,
            newest_thread_source=newest_source,
        )
        steps["pitr_target"] = point_in_time
        steps["incident_at"] = incident_at.isoformat()
        steps["rpo_note"] = f"restored to T; newest write at the incident was after it ({newest_before_t})"
        ok = (
            "passed" in steps["smoke_test"]
            and rate_rows_restored == 0
            and restored_before_replay[1] > 0
            and restored_after_replay[1] == 0
        )
        steps["result"] = "passed" if ok else "FAILED"
        return 0 if ok else 1
    finally:
        run("docker", "rm", "-f", STAGING_API, RESTORE, check=False)
        shutil.rmtree(work, ignore_errors=True)
        steps["restored_containers_deleted_at"] = datetime.now(UTC).isoformat()
        steps["started_at"] = started_at.isoformat()
        print(json.dumps(steps, indent=2, default=str))


def psql_ready(target: str) -> bool:
    result = subprocess.run(  # noqa: S603  # nosec B603
        ["docker", "exec", target, "psql", "-U", "neuron_owner", "-d", "neuron", "-tAc",
         "SELECT NOT pg_is_in_recovery()"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    return result.stdout.strip() == "t"


def reference_env() -> dict[str, str]:
    """The reference replicas' settings, read back from a running replica (no secrets on argv)."""
    raw = run("docker", "inspect", "-f", "{{json .Config.Env}}", container("api1"))
    return dict(item.split("=", 1) for item in json.loads(raw) if item.startswith("APP_"))


def env_args(env: dict[str, str]) -> list[str]:
    skip = {"APP_POSTGRES_DSN", "APP_POSTGRES_MIGRATION_DSN"}
    return [x for k, v in env.items() if k not in skip for x in ("-e", f"{k}={v}")]


if __name__ == "__main__":
    raise SystemExit(main())
