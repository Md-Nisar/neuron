from __future__ import annotations

import uuid
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AgentExecutionError, ThreadNotFoundError
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio


def _service(checkpointer: str = "memory") -> AgentService:
    return AgentService(Settings(env="test", checkpointer=checkpointer))


@pytest.mark.usefixtures("echo_agent")
async def test_second_turn_sees_first_turn() -> None:
    service = _service()
    first = await service.invoke(AgentRequest(message="my name is Ada"))
    second = await service.invoke(
        AgentRequest(message="what is my name?", thread_id=first.thread_id)
    )

    assert second.thread_id == first.thread_id
    assert second.answer == "my name is Ada | what is my name?"


@pytest.mark.usefixtures("echo_agent")
async def test_requests_without_thread_id_get_new_isolated_threads() -> None:
    service = _service()
    first = await service.invoke(AgentRequest(message="one"))
    second = await service.invoke(AgentRequest(message="two"))

    assert first.thread_id != second.thread_id
    assert uuid.UUID(second.thread_id).version == 4
    assert second.answer == "two"


@pytest.mark.usefixtures("echo_agent")
async def test_unknown_thread_is_rejected() -> None:
    with pytest.raises(ThreadNotFoundError):
        await _service().invoke(AgentRequest(message="hi", thread_id=str(uuid.uuid4())))


@pytest.mark.usefixtures("echo_agent")
async def test_thread_cannot_be_continued_by_another_user() -> None:
    service = _service()
    owned = await service.invoke(AgentRequest(message="secret", user_id="alice"))

    for other in ("mallory", None):
        with pytest.raises(ThreadNotFoundError) as excinfo:
            await service.invoke(
                AgentRequest(message="hi", thread_id=owned.thread_id, user_id=other)
            )
        # Same error as a missing thread: existence is not revealed.
        assert excinfo.value.context.code == "thread_not_found"

    continued = await service.invoke(
        AgentRequest(message="again", thread_id=owned.thread_id, user_id="alice")
    )
    assert continued.answer == "secret | again"


@pytest.mark.usefixtures("echo_agent")
async def test_anonymous_thread_cannot_be_claimed_by_a_user() -> None:
    service = _service()
    anonymous = await service.invoke(AgentRequest(message="hi"))
    with pytest.raises(ThreadNotFoundError):
        await service.invoke(
            AgentRequest(message="x", thread_id=anonymous.thread_id, user_id="bob")
        )


@pytest.mark.usefixtures("echo_agent")
async def test_thread_id_is_only_a_correlation_id_without_persistence() -> None:
    supplied = str(uuid.uuid4())
    first = await _service("none").invoke(AgentRequest(message="one", thread_id=supplied))
    assert first.thread_id == supplied
    assert first.answer == "one"


async def test_turns_persist_only_user_messages_and_final_answers(echo_agent: Any) -> None:
    service = _service()
    first = await service.invoke(AgentRequest(message="one"))
    await service.invoke(AgentRequest(message="two", thread_id=first.thread_id))

    state = await service.graph.aget_state({"configurable": {"thread_id": first.thread_id}})
    messages = state.values["messages"]
    assert [type(m) for m in messages] == [HumanMessage, AIMessage, HumanMessage, AIMessage]
    assert [m.content for m in messages] == ["one", "one", "two", "one | two"]


async def test_failed_turn_leaves_no_dangling_user_message(echo_agent: Any) -> None:
    service = _service()
    first = await service.invoke(AgentRequest(message="one"))
    echo_agent.fail_next = True
    with pytest.raises(AgentExecutionError):
        await service.invoke(AgentRequest(message="lost", thread_id=first.thread_id))

    retried = await service.invoke(AgentRequest(message="two", thread_id=first.thread_id))
    assert retried.answer == "one | two"


async def test_per_run_fields_are_reset_each_turn(echo_agent: Any) -> None:
    service = _service()
    first = await service.invoke(AgentRequest(message="one"))
    second = await service.invoke(AgentRequest(message="two", thread_id=first.thread_id))

    state = await service.graph.aget_state({"configurable": {"thread_id": first.thread_id}})
    assert state.values["request_id"] == second.request_id != first.request_id
    assert state.values["user_message"] is None
    assert state.values["answer"].answer == second.answer


async def test_inner_agent_state_is_never_checkpointed() -> None:
    # Regression: the create_agent subgraph inherited the thread checkpointer and stored its
    # internal state (tool calls/results) under an `agent:<id>` namespace.
    service = _service()
    first = await service.invoke(AgentRequest(message="one"))
    await service.invoke(AgentRequest(message="two", thread_id=first.thread_id))

    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    namespaces = {
        checkpoint.config["configurable"]["checkpoint_ns"]
        async for checkpoint in checkpointer.alist(None)
    }
    assert namespaces == {""}
