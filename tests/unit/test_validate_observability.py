"""`scripts/validate_observability.py` (#155): pinned validators that fail on bad files."""

from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest
from scripts import validate_observability as vo

ROOT = Path(__file__).resolve().parents[2]
_BIN_DIR_ENV = "NEURON_OBSERVABILITY_BIN_DIR"


def test_pins_name_a_version_a_github_release_asset_and_a_sha256() -> None:
    assert {pin.binary for pin in vo.PINS} == {"promtool", "otelcol-contrib"}
    for pin in vo.PINS:
        assert re.fullmatch(r"[0-9a-f]{64}", pin.sha256), pin.binary
        assert re.fullmatch(r"\d+\.\d+\.\d+", pin.version)
        assert pin.url.startswith("https://github.com/")
        assert f"/releases/download/v{pin.version}/" in pin.url
        assert pin.url.endswith(("linux-amd64.tar.gz", "linux_amd64.tar.gz"))
        assert pin.member.endswith(pin.binary)


def test_the_collector_pin_is_the_version_the_config_was_written_for() -> None:
    config = (ROOT / "deploy" / "observability" / "otel-collector.yaml").read_text("utf-8")
    assert f"opentelemetry-collector-contrib:{vo.OTELCOL.version}" in config


def _archive(member: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
        other = tarfile.TarInfo("../escape")
        other.size = 1
        tar.addfile(other, io.BytesIO(b"x"))
    return buffer.getvalue()


def _serve(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    def download(url: str, destination: Path) -> str:
        destination.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(vo, "_download", download)


def test_fetch_extracts_only_the_named_binary_when_the_hash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _archive("tool-1/promtool", b"binary")
    _serve(monkeypatch, data)
    pin = vo.Pin(
        "promtool",
        "1",
        "https://example.test/x.tar.gz",
        hashlib.sha256(data).hexdigest(),
        "tool-1/promtool",
    )
    path = vo.fetch(pin, tmp_path / "bin")
    assert path == tmp_path / "bin" / "promtool" and path.read_bytes() == b"binary"
    assert os.access(path, os.X_OK) or sys.platform == "win32"
    assert sorted(p.name for p in (tmp_path / "bin").iterdir()) == ["promtool"]
    assert not (tmp_path / "escape").exists()


def test_fetch_refuses_an_archive_that_does_not_match_the_pinned_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, _archive("tool-1/promtool", b"tampered"))
    pin = vo.Pin("promtool", "1", "https://example.test/x.tar.gz", "0" * 64, "tool-1/promtool")
    with pytest.raises(vo.ChecksumError):
        vo.fetch(pin, tmp_path / "bin")
    assert not (tmp_path / "bin" / "promtool").exists()  # nothing extracted


def test_main_exits_2_without_running_anything_on_a_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _serve(monkeypatch, b"not the pinned archive")
    ran: list[object] = []
    monkeypatch.setattr(vo, "run", lambda command: ran.append(command) or True)
    assert vo.main(["check", "--bin-dir", str(tmp_path)]) == 2
    assert ran == [] and "cannot obtain the validators" in capsys.readouterr().err


def test_downloads_must_be_https() -> None:
    with pytest.raises(ValueError, match="https"):
        vo._download("http://example.test/x.tar.gz", Path("unused"))


def test_run_reports_the_exit_status_of_the_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert vo.run([sys.executable, "-c", "raise SystemExit(0)"]) is True
    assert vo.run([sys.executable, "-c", "print('bad rule'); raise SystemExit(3)"]) is False
    assert "bad rule" in capsys.readouterr().out


def _fake_tools(monkeypatch: pytest.MonkeyPatch, rejects: set[str]) -> list[str]:
    """Replace the subprocess: a command fails when its file argument is in `rejects`."""
    seen: list[str] = []

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        seen.append(Path(command[-1].removeprefix("--config=")).name)
        failed = Path(command[-1].removeprefix("--config=")).name in rejects
        return subprocess.CompletedProcess(command, 1 if failed else 0, "", "boom" * failed)

    monkeypatch.setattr(vo.subprocess, "run", fake_run)
    return seen


def test_check_fails_when_either_tool_rejects_and_still_runs_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = (Path("promtool"), Path("otelcol-contrib"))
    rules, config = Path("rules.yaml"), Path("collector.yaml")
    seen = _fake_tools(monkeypatch, set())
    assert vo.check(*tools, rules, config) is True and seen == ["rules.yaml", "collector.yaml"]
    seen = _fake_tools(monkeypatch, {"rules.yaml"})
    assert vo.check(*tools, rules, config) is False and seen == ["rules.yaml", "collector.yaml"]
    seen = _fake_tools(monkeypatch, {"collector.yaml"})
    assert vo.check(*tools, rules, config) is False and len(seen) == 2


def test_reject_broken_needs_both_tools_to_reject_and_both_real_files_to_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = (Path("promtool"), Path("otelcol-contrib"))
    broken = {vo.BROKEN_RULES.name, vo.BROKEN_COLLECTOR.name}
    _fake_tools(monkeypatch, broken)
    assert vo.reject_broken(*tools) is True
    _fake_tools(monkeypatch, {vo.BROKEN_RULES.name})  # otelcol accepts its broken file
    assert vo.reject_broken(*tools) is False
    _fake_tools(monkeypatch, {vo.BROKEN_COLLECTOR.name})  # promtool accepts its broken file
    assert vo.reject_broken(*tools) is False
    _fake_tools(monkeypatch, broken | {vo.RULES.name})  # a real file that fails
    assert vo.reject_broken(*tools) is False


def test_the_collector_check_gets_a_placeholder_backend_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.delenv("OTEL_BACKEND_ENDPOINT", raising=False)
    monkeypatch.setattr(vo.subprocess, "run", fake_run)
    assert vo.run(["otelcol-contrib", "validate"]) is True
    assert captured["OTEL_BACKEND_ENDPOINT"] == vo.PLACEHOLDER_ENV["OTEL_BACKEND_ENDPOINT"]


def test_the_broken_fixtures_are_valid_yaml_files_that_exist() -> None:
    import yaml

    for path in (vo.BROKEN_RULES, vo.BROKEN_COLLECTOR):
        assert isinstance(yaml.safe_load(path.read_text("utf-8")), dict), path


# The real tools. CI runs them through the `observability-config` job; here they run when a
# directory holding `promtool` and `otelcol-contrib` is named, for example one that
# `scripts/validate_observability.py check --bin-dir DIR` filled.
_real = pytest.mark.skipif(
    not os.environ.get(_BIN_DIR_ENV), reason=f"{_BIN_DIR_ENV} names no directory of validators"
)


def _real_tools() -> tuple[Path, Path]:
    directory = Path(os.environ[_BIN_DIR_ENV])
    return directory / "promtool", directory / "otelcol-contrib"


@_real
def test_the_real_tools_accept_the_repository_files() -> None:
    assert vo.check(*_real_tools(), vo.RULES, vo.COLLECTOR) is True


@_real
def test_the_real_tools_each_reject_their_broken_file() -> None:
    promtool, otelcol = _real_tools()
    assert vo.check(promtool, otelcol, vo.BROKEN_RULES, vo.COLLECTOR) is False
    assert vo.check(promtool, otelcol, vo.RULES, vo.BROKEN_COLLECTOR) is False
    assert vo.reject_broken(promtool, otelcol) is True
