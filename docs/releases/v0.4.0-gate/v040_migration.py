"""Run with the release candidate against the database v0.3.0 wrote (ADR 0006 migration)."""
import asyncio, json, subprocess, os
from datetime import UTC, datetime, timedelta
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ThreadNotFoundError
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.auth import Principal
from neuron_agent.services.agent_service import AgentService

DSN = "postgresql://postgres@/neuron_migration?host=/var/tmp/neuron-pg&port=55432"
threads = json.load(open("/var/tmp/gate/v030_threads.json"))
legacy = [t["thread_id"] for t in threads if t["user"] == "legacy-user"]

def check(name, ok, observed):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {observed}", flush=True)

async def raises_not_found(call):
    try:
        await call
    except ThreadNotFoundError:
        return True
    return False

async def main():
    common = dict(checkpointer="postgres", postgres_dsn=DSN, checkpointer_setup_on_startup=True)
    jwt_settings = Settings(env="development", auth_mode="jwt", auth_issuer="https://idp.gate.test/",
                            auth_audience="neuron-api", auth_jwks_url="http://127.0.0.1:1/jwks.json",
                            identity_hash_key="m" * 40, **common)
    principal = Principal(issuer="https://idp.gate.test/", subject="legacy-user",
                          scopes=frozenset({"agent:invoke", "threads:read", "threads:delete"}),
                          token_id=None, expires_at=datetime.now(UTC) + timedelta(minutes=5))
    service = AgentService(jwt_settings)
    await service.startup()  # also runs setup: LangGraph migrations + the owner index
    try:
        denied = [await raises_not_found(service.get_history(t, None, limit=10, offset=0, principal=principal)) for t in legacy]
        check("jwt mode: the same person's v0.3 threads are 404 (no dual-hash fallback)", all(denied), denied)
        cont = await raises_not_found(service.invoke(AgentRequest(message="continue", thread_id=legacy[0]), principal=principal))
        check("jwt mode: continuing a v0.3 thread is 404", cont, cont)
        listed = await service.list_user_threads(None, limit=50, offset=0, principal=principal)
        check("jwt mode: v0.3 threads are not listed", listed.total == 0, f"total={listed.total}")
        erased = await service.erase_user_data(None, principal=principal)
        check("jwt mode: erase-all leaves v0.3 threads alone", erased.erased_count == 0, erased)
        fresh = await service.invoke(AgentRequest(message="new v0.4 thread"), principal=principal)
        listed = await service.list_user_threads(None, limit=50, offset=0, principal=principal)
        check("jwt mode: new threads work alongside the old data", [t.thread_id for t in listed.threads] == [fresh.thread_id], f"total={listed.total}")
    finally:
        await service.shutdown()

    none_service = AgentService(Settings(env="development", auth_mode="none", **common))
    await none_service.startup()
    try:
        history = await none_service.get_history(legacy[0], "legacy-user", limit=10, offset=0)
        check("none mode (development): v0.3 owner hash still reads its thread", history.total == 4, f"{history.total} messages")
        foreign = await raises_not_found(none_service.get_history(legacy[0], "other-user", limit=10, offset=0))
        check("none mode: another v0.3 user still gets 404", foreign, foreign)
    finally:
        await none_service.shutdown()

    pruned = subprocess.run(["python", "-m", "neuron_agent.persistence.cli", "prune", "--older-than-days", "0"],
                            env={**os.environ, "APP_ENV": "development", "APP_CHECKPOINTER": "postgres", "APP_POSTGRES_DSN": DSN},
                            capture_output=True, text=True)
    check("retention removes the legacy threads (prune --older-than-days 0)", pruned.returncode == 0,
          [line for line in pruned.stdout.splitlines() if "thread_prune_job_completed" in line][-1][:160])

asyncio.run(main())
