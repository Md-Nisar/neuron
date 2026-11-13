"""The operator's `reindex` command line (RAG-09.04): checked before it touches a database."""

from __future__ import annotations

import pytest

from neuron_agent.config.settings import Settings
from neuron_agent.persistence import cli


@pytest.mark.parametrize(
    "argv", [["reindex"], ["setup", "start"], ["prune", "cancel"], ["reindex", "restart"]]
)
def test_reindex_needs_its_action_and_nothing_else_takes_one(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == 2


def test_reindex_refuses_with_the_knowledge_engine_off(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli._reindex(Settings(env="test", knowledge_enabled=False), "status")
    assert "APP_KNOWLEDGE_ENABLED" in capsys.readouterr().err


def test_reindex_start_needs_the_target_model(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(
        env="test",
        knowledge_enabled=True,
        checkpointer="postgres",
        postgres_dsn="postgresql://u:secret@db/neuron",  # type: ignore[arg-type]
    )
    with pytest.raises(SystemExit):
        cli._reindex(settings, "start")
    err = capsys.readouterr().err
    assert "APP_KNOWLEDGE_REINDEX_EMBEDDING_" in err
    assert "secret" not in err
