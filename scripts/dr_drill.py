# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Restore drill on the reference stack (ADR 0012 decision 8, #332). Local use only.

    KNOWLEDGE_ENABLED=true NEURON_IMAGE=neuron:ref make reference-up
    KNOWLEDGE_ENABLED=true NEURON_IMAGE=neuron:ref docker compose \
        -f docker-compose.reference.yml --profile knowledge up -d --no-deps worker
    NEURON_IMAGE=neuron:ref uv run python -m scripts.dr_drill

Follows OPERATIONS.md, "Backups and restore", on the reference stack's Postgres (WAL archiving
on): seed threads and memories, take a base backup, write more, record a point in time T, erase
one user's data after T, then restore to T into a *new* container, run `setup`, point a
throwaway API replica at it and run the smoke test, replay the erasure, check the `UNLOGGED`
rate-limit table came back empty, and delete everything the drill created. Prints the template
fields of the runbook, including RTO and RPO. Needs Docker and the running reference stack.

Knowledge (RAG-07.03): a known Markdown document and one more are ingested before the backup.
After T one document is uploaded and the other deleted, then the blob volume is copied: files
and database from different moments. After the restore, `neuron-worker check-blobs` must report
the orphan file and flag the deleted document's missing file, and the staging replica must cite
the known document for its question. The worker needs only the Markdown parser, so docling-serve
is not started (`--no-deps`).
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
from scripts.smoke_test import KNOWLEDGE_DOCUMENT, KNOWLEDGE_QUESTION, _request

COMPOSE = ["docker", "compose", "-f", "docker-compose.reference.yml"]
# The reference stack's image: the knowledge tables need pgvector.
POSTGRES_IMAGE = (
    "pgvector/pgvector:pg16@sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f"
)
API = "http://127.0.0.1:8101"
RESTORE = "neuron-dr-restore"
STAGING_API = "neuron-dr-staging"
RESTORE_API_PORT = 8199
NETWORK = "neuron_default"
BLOB_ROOT = "/var/lib/neuron/knowledge-blobs"
BLOB_VOLUME = "neuron_knowledge-blobs"
RESTORED_BLOBS = "neuron-dr-blobs"
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
    except OSError:  # not listening yet, or reset while starting
        return 0, ""


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


def seed(token: str, threads: int, memories: int) -> int:
    """Seed threads and memories; return how many memories were saved.

    With knowledge on, a run's first model call must search, so the fake model's scripted
    `remember:` turn ends without asking to save a memory, as a plain thread."""
    for index in range(threads):
        stream(token, f"hello {index}")
    saved = 0
    for index in range(memories):
        paused = stream(token, f"remember: drill note {index}")
        if "approval" in paused:
            path = (
                f"/v1/threads/{paused['thread_id']}/approvals/{paused['approval']['approval_id']}"
            )
            saved += api("POST", path, token, {"decision": "approve"})[0] == 200
    return saved


def thread_total(token: str, base: str = API) -> int:
    status, text = api("GET", "/v1/me/threads?limit=1", token, base=base)
    return int(json.loads(text)["total"]) if status == 200 else -1


def upload(token: str, kb_id: str, name: str, content: bytes) -> str:
    """Upload a Markdown file and wait until it is ready; return its id."""
    path = f"/v1/knowledge/bases/{kb_id}/documents"
    doc_id = str(
        _request("upload", "POST", API, path, 60, token=token, upload=(name, content))["doc_id"]
    )
    wait_for(f"{name} to be ready", lambda: document(token, doc_id).get("status") == "ready")
    return doc_id


def document(token: str, doc_id: str) -> dict[str, Any]:
    status, text = api("GET", f"/v1/knowledge/documents/{doc_id}", token)
    return json.loads(text) if status == 200 else {"http": status}


def cited(token: str, kb_id: str, base: str) -> list[str]:
    """The documents the answer to the known question cites."""
    body = {"message": KNOWLEDGE_QUESTION, "knowledge_base_ids": [kb_id]}
    reply = _request("cite", "POST", base, "/v1/agent/invoke", 60, token=token, body=body)
    return [str(c["doc_id"]) for c in reply.get("citations") or []] if reply.get("grounded") else []


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
        steps["memories_seeded"] = seed(alice.get(), threads=3, memories=2)
        seed(bob.get(), threads=3, memories=0)
        kb_id = str(
            _request("base", "POST", API, "/v1/knowledge/bases", 60, token=alice.get(),
                     body={"name": "restore drill"})["kb_id"]
        )  # fmt: skip
        known = upload(alice.get(), kb_id, "known.md", KNOWLEDGE_DOCUMENT)
        doomed = upload(alice.get(), kb_id, "deleted.md", b"# Drill\n\nDeleted after T.\n")
        steps["knowledge_cited_on_source"] = known in cited(alice.get(), kb_id, API)
        before_backup = thread_total(alice.get()), thread_total(bob.get())
        psql(source, "SELECT pg_switch_wal()")
        run("docker", "exec", "-u", "postgres", source, "rm", "-rf", "/var/lib/postgresql/backup")
        run(
            "docker", "exec", "-u", "postgres", source, "pg_basebackup", "-D",
            "/var/lib/postgresql/backup", "-Fp", "-X", "none", "-c", "fast", "-U", "neuron_owner",
        )  # fmt: skip
        steps["backup_taken"] = datetime.now(UTC).isoformat()
        # Segments older than the backup's first WAL file are not needed to restore from it; the
        # reference stack's load tests leave hundreds of them (16 MB each).
        label = run("docker", "exec", source, "cat", "/var/lib/postgresql/backup/backup_label")
        first_wal = label.split("file ")[1].split(")")[0]
        run(
            "docker", "exec", source, "sh", "-c",
            f"cd /var/lib/postgresql/wal_archive && for f in $(ls | grep -v history); do "
            f'[ "$f" \\< "{first_wal}" ] && rm -f "$f"; done; true',
        )  # fmt: skip
        # 2. Write more, record the point in time T, then bob erases his data after T.
        seed(alice.get(), threads=2, memories=0)
        time.sleep(2)
        point_in_time = psql(source, "SELECT clock_timestamp()")
        newest_before_t = psql(source, "SELECT now()")
        time.sleep(2)
        status, erased = api("DELETE", "/v1/me/threads", bob.get())
        seed(alice.get(), threads=1, memories=0)
        late = upload(alice.get(), kb_id, "late.md", b"# Drill\n\nUploaded after T.\n")
        api("DELETE", f"/v1/knowledge/documents/{doomed}", alice.get())
        # The purge deletes the file and the row; the restored row at T keeps pointing to it.
        wait_for("the purge", lambda: document(alice.get(), doomed).get("http") == 404)
        # The file backup, taken at the incident: a later moment than the database's T.
        run("docker", "volume", "rm", "-f", RESTORED_BLOBS, check=False)
        run(
            "docker", "run", "--rm", "-u", "0", "--entrypoint", "cp",
            "-v", f"{BLOB_VOLUME}:/from:ro", "-v", f"{RESTORED_BLOBS}:/to",
            os.environ["NEURON_IMAGE"], "-a", "/from/.", "/to/",
        )  # fmt: skip
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
        run("chmod", "-R", "a+rX", str(work / "archive"))
        run("docker", "rm", "-f", RESTORE, check=False)
        run(
            "docker", "run", "-d", "--name", RESTORE, "--network", NETWORK,
            "-v", f"{work / 'backup'}:/var/lib/postgresql/data",
            "-v", f"{work / 'archive'}:/archive:ro", POSTGRES_IMAGE,
            "postgres", "-c", "restore_command=cp /archive/%f %p",
            "-c", f"recovery_target_time={point_in_time}",
            "-c", "recovery_target_action=promote", "-c", "recovery_target_inclusive=true",
        )  # fmt: skip
        try:
            wait_for("the restored database", lambda: psql_ready(RESTORE), seconds=300)
        except SystemExit:
            print(
                run("sh", "-c", f"docker logs --tail 60 {RESTORE} 2>&1", check=False),
                file=sys.stderr,
            )
            raise
        steps["restore_usable_seconds"] = round(time.monotonic() - restore_started, 1)
        # Counted before any replica touches the database: the limiter writes to this table.
        rate_rows_restored = int(psql(RESTORE, "SELECT count(*) FROM neuron_rate_buckets"))

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
        # 4b. Files and rows from different moments: check before any worker runs on them.
        check = subprocess.run(  # noqa: S603  # nosec B603
            ["docker", "run", "--rm", "--network", NETWORK, "-v", f"{RESTORED_BLOBS}:{BLOB_ROOT}",
             "-e", "APP_ENV=development", "-e", f"APP_KNOWLEDGE_BLOB_ROOT={BLOB_ROOT}",
             "-e", f"APP_POSTGRES_WORKER_DSN=postgresql://neuron_worker@{RESTORE}:5432/neuron"
             "?sslmode=disable", "-e", f"PGPASSWORD={worker_password()}",
             os.environ["NEURON_IMAGE"], "neuron-worker", "check-blobs"],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        try:
            report = json.loads(check.stdout)
        except ValueError:  # the check failed: its exit code and stderr say why
            report = {"stderr": check.stderr[-400:]}
        steps["check_blobs"] = {"exit": check.returncode, **report}
        run("docker", "rm", "-f", STAGING_API, check=False)
        run(
            "docker", "run", "-d", "--name", STAGING_API, "--network", NETWORK,
            "-p", f"127.0.0.1:{RESTORE_API_PORT}:8000", *env_args(env),
            "-v", f"{RESTORED_BLOBS}:{BLOB_ROOT}",
            "-e", f"APP_POSTGRES_DSN=postgresql://neuron_app:{APP_PASSWORD}@{RESTORE}:5432/neuron"
            "?sslmode=disable",
            os.environ["NEURON_IMAGE"],
        )  # fmt: skip
        staging = f"http://127.0.0.1:{RESTORE_API_PORT}"
        wait_for(
            "the staging replica", lambda: api("GET", "/health/ready", "x", base=staging)[0] == 200
        )
        smoke = subprocess.run(  # noqa: S603  # nosec B603
            [sys.executable, "scripts/smoke_test.py", staging],
            env={**os.environ, "SMOKE_TEST_TOKEN": alice.get()},
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        steps["smoke_test"] = (smoke.stdout + smoke.stderr).strip()
        steps["restore_to_smoke_test_passed_seconds"] = round(time.monotonic() - restore_started, 1)

        # 5. Counts, the erasure replay, and the UNLOGGED table.
        restored_before_replay = (
            thread_total(alice.get(), staging),
            thread_total(bob.get(), staging),
        )
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
        # After the counts above: the answer adds a thread to the restored database.
        steps["knowledge_cited_after_restore"] = known in cited(alice.get(), kb_id, staging)
        steps["knowledge_documents"] = {
            "known": known,
            "deleted_after_T": doomed,
            "uploaded_after_T": late,
        }
        steps["pitr_target"] = point_in_time
        steps["incident_at"] = incident_at.isoformat()
        steps["rpo_note"] = (
            f"restored to T; newest write at the incident was after it ({newest_before_t})"
        )
        ok = (
            "passed" in steps["smoke_test"]
            and rate_rows_restored == 0
            and restored_before_replay[1] > 0
            and restored_after_replay[1] == 0
            and steps["knowledge_cited_after_restore"]
            and check.returncode == 1
            and report.get("missing_blobs") == [doomed]
            and report.get("orphan_blobs", 0) >= 1
        )
        steps["result"] = "passed" if ok else "FAILED"
        return 0 if ok else 1
    finally:
        run("docker", "rm", "-f", STAGING_API, RESTORE, check=False)
        run("docker", "volume", "rm", "-f", RESTORED_BLOBS, check=False)
        shutil.rmtree(work, ignore_errors=True)
        steps["restored_containers_deleted_at"] = datetime.now(UTC).isoformat()
        steps["started_at"] = started_at.isoformat()
        print(json.dumps(steps, indent=2, default=str))


def psql_ready(target: str) -> bool:
    if run("docker", "inspect", "-f", "{{.State.Running}}", target) != "true":
        raise SystemExit("the restore container stopped")
    result = subprocess.run(  # noqa: S603  # nosec B603
        ["docker", "exec", target, "psql", "-U", "neuron_owner", "-d", "neuron", "-tAc",
         "SELECT NOT pg_is_in_recovery()"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    return result.stdout.strip() == "t"


def reference_env() -> dict[str, str]:
    """The reference replicas' settings, read from a running replica (throwaway local values)."""
    raw = run("docker", "inspect", "-f", "{{json .Config.Env}}", container("api1"))
    return dict(item.split("=", 1) for item in json.loads(raw) if item.startswith("APP_"))


def worker_password() -> str:
    """The worker's throwaway database password, read from the running worker."""
    raw = run("docker", "inspect", "-f", "{{json .Config.Env}}", container("worker"))
    return next(i.split("=", 1)[1] for i in json.loads(raw) if i.startswith("PGPASSWORD="))


def env_args(env: dict[str, str]) -> list[str]:
    skip = {"APP_POSTGRES_DSN", "APP_POSTGRES_MIGRATION_DSN"}
    return [x for k, v in env.items() if k not in skip for x in ("-e", f"{k}={v}")]


if __name__ == "__main__":
    raise SystemExit(main())
