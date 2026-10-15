"""Run with the v0.3.0 checkout: create threads exactly as v0.3.0 stores them."""
import asyncio, json
from neuron_agent.config.settings import Settings
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

async def main():
    settings = Settings(env="development", checkpointer="postgres", checkpointer_setup_on_startup=True,
                        postgres_dsn="postgresql://postgres@/neuron_migration?host=/var/tmp/neuron-pg&port=55432")
    service = AgentService(settings)
    await service.startup()
    try:
        threads = []
        for user in ("legacy-user", "legacy-user", "other-user"):
            first = await service.invoke(AgentRequest(message=f"v0.3 turn for {user}", user_id=user))
            await service.invoke(AgentRequest(message="second turn", user_id=user, thread_id=first.thread_id))
            threads.append({"user": user, "thread_id": first.thread_id})
        print(json.dumps(threads))
    finally:
        await service.shutdown()

asyncio.run(main())
