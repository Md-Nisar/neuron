"""Local development tokens (`scripts/dev_token.py`, #62)."""

from __future__ import annotations

import json
import stat
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from scripts import dev_token

from neuron_agent.config.settings import Settings
from neuron_agent.security.auth import TokenVerifier
from neuron_agent.security.authorization import DEV_PERMISSIONS


@pytest.fixture
def served(tmp_path: Path) -> Iterator[str]:
    """Serve the JWKS for `tmp_path` on an ephemeral loopback port; yield its URL."""
    dev_token.ensure_keys(tmp_path)
    server = dev_token.jwks_server(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/jwks.json"
    server.shutdown()
    server.server_close()


def _dev_settings(jwks_url: str, **overrides: Any) -> Settings:
    return Settings(
        **{
            "env": "development",
            "auth_mode": "jwt",
            "auth_issuer": dev_token.DEV_ISSUER,
            "auth_audience": dev_token.DEV_AUDIENCE,
            "auth_jwks_url": jwks_url,
            "identity_hash_key": "k" * 32,
            **overrides,
        }
    )


def test_minted_token_is_accepted_by_the_real_verifier(tmp_path: Path, served: str) -> None:
    settings = _dev_settings(served)
    token = dev_token.mint(
        settings,
        tmp_path,
        subject="ada",
        scopes=" ".join(sorted(DEV_PERMISSIONS)),
        ttl=timedelta(minutes=5),
    )

    principal = anyio.run(TokenVerifier(settings).verify, f"Bearer {token}")

    assert principal.subject == "ada"
    assert principal.issuer == dev_token.DEV_ISSUER
    assert principal.scopes == DEV_PERMISSIONS


def test_tokens_satisfy_a_server_that_requires_the_access_token_type(
    tmp_path: Path, served: str
) -> None:
    settings = _dev_settings(served, auth_require_typ=True)
    token = dev_token.mint(
        settings, tmp_path, subject="ada", scopes="agent:invoke", ttl=timedelta(minutes=5)
    )

    assert anyio.run(TokenVerifier(settings).verify, f"Bearer {token}").subject == "ada"


def test_setup_creates_a_private_key_once_and_a_stable_jwks(tmp_path: Path) -> None:
    _, first_kid = dev_token.ensure_keys(tmp_path)
    _, second_kid = dev_token.ensure_keys(tmp_path)

    key_mode = stat.S_IMODE((tmp_path / "jwt-private.pem").stat().st_mode)
    assert key_mode == 0o600
    assert first_kid == second_kid
    [jwk] = json.loads((tmp_path / "jwks.json").read_text())["keys"]
    assert jwk["kid"] == first_kid
    assert jwk["alg"] == "ES256"
    assert "d" not in jwk  # public key only


def test_jwks_server_serves_only_the_jwks(served: str) -> None:
    with urllib.request.urlopen(served) as response:  # noqa: S310 - loopback test server
        assert "keys" in json.load(response)
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(served.replace("jwks.json", "jwt-private.pem"))  # noqa: S310
    assert excinfo.value.code == 404


def test_env_block_configures_jwt_mode_for_the_dev_issuer() -> None:
    lines = dict(line.split("=", 1) for line in dev_token.env_block().splitlines() if "=" in line)

    assert lines["APP_AUTH_MODE"] == "jwt"
    assert lines["APP_AUTH_ISSUER"] == dev_token.DEV_ISSUER
    assert lines["APP_AUTH_JWKS_URL"].startswith("http://127.0.0.1:")
    assert len(lines["APP_IDENTITY_HASH_KEY"]) >= 32
    assert (
        lines["APP_IDENTITY_HASH_KEY"]
        != dict(line.split("=", 1) for line in dev_token.env_block().splitlines() if "=" in line)[
            "APP_IDENTITY_HASH_KEY"
        ]
    )


@pytest.mark.parametrize("env", ["test", "staging", "production"])
@pytest.mark.parametrize("command", [["setup"], ["serve"], []])
def test_every_command_refuses_outside_development(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    env: str,
    command: list[str],
) -> None:
    monkeypatch.setattr(
        dev_token, "Settings", lambda: Settings.model_construct(env=env, auth_mode="jwt")
    )

    assert dev_token.main(command, directory=tmp_path) == 2
    assert f"refused when APP_ENV={env}" in capsys.readouterr().err
    assert not (tmp_path / "jwt-private.pem").exists()


def test_token_command_explains_setup_when_the_api_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(dev_token, "Settings", lambda: Settings(env="development"))

    assert dev_token.main([], directory=tmp_path) == 2
    assert "dev_token.py setup >> .env" in capsys.readouterr().err
