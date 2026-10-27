"""The MCP server list (#238): what is accepted and what is refused at load."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ConfigurationError
from neuron_agent.tools.mcp.config import (
    MAX_SERVERS,
    load_mcp_config,
    parse_mcp_config,
    validate_mcp_url,
)

_PIN = "sha256:" + "a" * 64
_TOKENS = {"units": SecretStr("s3cret-token")}


def _server(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "units",
        "url": "https://mcp.example.com/mcp",
        "tools": [{"name": "convert_units", "pin": _PIN}],
        **overrides,
    }


def _settings(**overrides: Any) -> Settings:
    return Settings(env="test", **{"mcp_bearer_tokens": _TOKENS, **overrides})


def _parse(*servers: dict[str, Any], tokens: tuple[str, ...] = ("units",)) -> Any:
    return parse_mcp_config(json.dumps({"servers": list(servers)}), env="test", token_names=tokens)


def test_a_valid_server_loads_with_the_safe_defaults() -> None:
    [server] = _parse(_server()).servers
    assert server.auth == "bearer"
    assert [(t.name, t.risk) for t in server.tools] == [("convert_units", "mutating")]
    assert server.pins == {"convert_units": _PIN}


def test_unset_means_no_servers() -> None:
    settings = Settings(env="test")
    assert load_mcp_config(settings.mcp_servers, env="test", token_names=()).servers == []


def test_the_file_is_read_from_the_setting(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": [_server()]}), encoding="utf-8")
    settings = _settings(mcp_servers=path)
    config = load_mcp_config(
        settings.mcp_servers, env=settings.env, token_names=settings.mcp_bearer_tokens
    )
    assert [s.name for s in config.servers] == ["units"]


def test_a_missing_file_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot be read"):
        load_mcp_config(tmp_path / "absent.json", env="test", token_names=())


@pytest.mark.parametrize(
    ("overrides", "mentions"),
    [
        ({"command": "npx", "args": ["server"]}, "stdio"),
        ({"transport": "sse"}, "Streamable HTTP"),
        ({"transport": "stdio"}, "Streamable HTTP"),
        ({"headers": {"Authorization": "Bearer x"}}, "APP_MCP_BEARER_TOKENS"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_other_transports_and_unknown_keys_are_refused(
    overrides: dict[str, Any], mentions: str
) -> None:
    with pytest.raises(ConfigurationError, match=mentions):
        _parse(_server(**overrides))


@pytest.mark.parametrize(
    "tool",
    [
        {"name": "convert_units", "pin": "abc"},
        {"name": "convert_units", "pin": "sha256:" + "A" * 64},
        {"name": "Convert-Units", "pin": _PIN},
        {"name": "convert_units", "pin": _PIN, "risk": "safe"},
        {"name": "convert_units", "pin": _PIN, "readOnlyHint": True},
    ],
)
def test_malformed_tool_entries_are_refused(tool: dict[str, Any]) -> None:
    with pytest.raises(ConfigurationError):
        _parse(_server(tools=[tool]))


def test_duplicates_and_limits_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="twice"):
        _parse(_server(tools=[{"name": "a", "pin": _PIN}, {"name": "a", "pin": _PIN}]))
    with pytest.raises(ConfigurationError, match="twice"):
        _parse(_server(), _server())
    with pytest.raises(ConfigurationError):
        _parse(_server(tools=[]))
    many = [_server(name=f"s{n}") for n in range(MAX_SERVERS + 1)]
    with pytest.raises(ConfigurationError):
        parse_mcp_config(
            json.dumps({"servers": many}), env="test", token_names=[s["name"] for s in many]
        )


def test_invalid_json_is_a_configuration_error_without_the_content() -> None:
    with pytest.raises(ConfigurationError, match="not valid JSON") as error:
        parse_mcp_config("{ token: s3cret", env="test", token_names=())
    assert "s3cret" not in str(error.value)


def test_a_bearer_server_needs_its_token() -> None:
    with pytest.raises(ConfigurationError, match="units needs a token"):
        _parse(_server(), tokens=())


def test_an_auth_none_server_needs_no_token() -> None:
    config = _parse(_server(auth="none"), tokens=())
    assert config.servers[0].auth == "none"


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example.com/mcp",
        "ws://mcp.example.com/mcp",
        "https://user:pw@mcp.example.com/mcp",
        "https://10.0.0.5/mcp",
        "https://169.254.169.254/latest",
        "https://mcp.example.com/a b",
    ],
)
def test_unsafe_urls_are_refused_in_every_environment(url: str) -> None:
    for env in ("test", "staging", "production"):
        with pytest.raises(ConfigurationError):
            validate_mcp_url(url, env=env)


def test_https_public_urls_are_accepted() -> None:
    assert validate_mcp_url("https://mcp.example.com/mcp", env="production")


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8765/mcp", "http://localhost:9/mcp", "https://localhost/mcp"]
)
def test_loopback_http_is_for_development_and_test_only(url: str) -> None:
    assert validate_mcp_url(url, env="development") == url
    assert validate_mcp_url(url, env="test") == url
    for env in ("staging", "production"):
        with pytest.raises(ConfigurationError):
            validate_mcp_url(url, env=env)


def test_loopback_with_credentials_is_refused_even_in_development() -> None:
    with pytest.raises(ConfigurationError):
        validate_mcp_url("http://user:pw@127.0.0.1/mcp", env="development")


def test_the_url_rules_apply_when_a_file_is_parsed() -> None:
    with pytest.raises(ConfigurationError, match="https"):
        _parse(_server(url="http://mcp.example.com/mcp"))


def test_tokens_come_from_the_environment_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_MCP_BEARER_TOKENS", '{"units": "s3cret-token"}')
    settings = Settings(env="test")
    assert settings.mcp_bearer_tokens["units"].get_secret_value() == "s3cret-token"
    assert "s3cret-token" not in repr(settings)
