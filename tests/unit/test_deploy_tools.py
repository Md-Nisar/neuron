# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The deploy decisions: digest-only images, release checks, hooks never printed (#151)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest
from scripts import deploy_tools

DIGEST = "ghcr.io/md-nisar/neuron@sha256:" + "a" * 64
PYPROJECT = '[project]\nname = "neuron-agent"\nversion = "1.2.3"\n'
CHANGELOG = "# Changelog\n\n## Unreleased\n\n- next\n\n## 1.2.3\n\n- the release\n"
HOOK = "https://api.render.com/deploy/srv-abc?key=SECRETKEY"


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/md-nisar/neuron:sha-abc",
        "ghcr.io/md-nisar/neuron:latest",
        "ghcr.io/md-nisar/neuron",
        "ghcr.io/other/neuron@sha256:" + "a" * 64,
        "ghcr.io/md-nisar/neuron@sha256:" + "a" * 63,
        "ghcr.io/md-nisar/neuron@sha256:" + "G" * 64,
        DIGEST + "\n--extra",
    ],
)
def test_only_a_digest_reference_of_our_image_deploys(image: str) -> None:
    with pytest.raises(deploy_tools.DeployError):
        deploy_tools.check_image(image)


def test_a_digest_reference_is_accepted() -> None:
    deploy_tools.check_image(DIGEST)


def test_a_matching_tag_with_a_changelog_section_passes() -> None:
    assert deploy_tools.check_release("v1.2.3", PYPROJECT, CHANGELOG) == "1.2.3"


@pytest.mark.parametrize("tag", ["v1.2.3-rc.1", "v1.2.3-rc.12"])
def test_a_release_candidate_tag_is_checked_against_its_base_version(tag: str) -> None:
    assert deploy_tools.check_release(tag, PYPROJECT, CHANGELOG) == "1.2.3"


def test_a_release_candidate_of_another_version_or_without_a_section_is_refused() -> None:
    with pytest.raises(deploy_tools.DeployError, match="differs"):
        deploy_tools.check_release("v1.2.4-rc.1", PYPROJECT, CHANGELOG.replace("1.2.3", "1.2.4"))
    with pytest.raises(deploy_tools.DeployError, match="no section"):
        deploy_tools.check_release("v1.2.3-rc.1", PYPROJECT, "## 1.2.2\n\n")


@pytest.mark.parametrize(
    ("tag", "pyproject", "changelog", "message"),
    [
        ("1.2.3", PYPROJECT, CHANGELOG, "v1.2.3"),
        ("v1.2", PYPROJECT, CHANGELOG, "v1.2.3"),
        ("v1.2.3-rc.0", PYPROJECT, CHANGELOG, "v1.2.3"),
        ("v1.2.3-beta.1", PYPROJECT, CHANGELOG, "v1.2.3"),
        ("v1.2.3-rc", PYPROJECT, CHANGELOG, "v1.2.3"),
        ("v1.2.4", PYPROJECT, CHANGELOG.replace("1.2.3", "1.2.4"), "differs"),
        ("v1.2.3", PYPROJECT, "# Changelog\n\n## Unreleased\n\n- next\n", "no section"),
        ("v1.2.3", PYPROJECT, "## 1.2.3\n\n", "no section"),
    ],
)
def test_a_tag_that_disagrees_with_the_version_or_changelog_is_refused(
    tag: str, pyproject: str, changelog: str, message: str
) -> None:
    with pytest.raises(deploy_tools.DeployError, match=message):
        deploy_tools.check_release(tag, pyproject, changelog)


def test_every_requested_service_needs_a_render_hook() -> None:
    raw = json.dumps({"a": HOOK, "b": HOOK})
    assert set(deploy_tools.select_hooks(raw, ["a", "b"])) == {"a", "b"}
    with pytest.raises(deploy_tools.DeployError, match="no deploy hook for: c"):
        deploy_tools.select_hooks(raw, ["a", "c"])


@pytest.mark.parametrize(
    "raw",
    [None, "", "not json", "[]", '{"a": 1}', '{"a": "http://api.render.com/deploy/x"}'],
)
def test_missing_malformed_or_foreign_hooks_are_refused(raw: str | None) -> None:
    with pytest.raises(deploy_tools.DeployError):
        deploy_tools.select_hooks(raw, ["a"])


def test_a_hook_on_another_host_is_refused() -> None:
    raw = json.dumps({"a": "https://evil.example/deploy/srv-1?key=k"})
    with pytest.raises(deploy_tools.DeployError, match="not an https://api.render.com"):
        deploy_tools.select_hooks(raw, ["a"])


def test_the_image_is_added_to_the_hook_and_its_key_is_kept() -> None:
    url = deploy_tools.hook_request_url(HOOK + "&imgURL=old", DIGEST)
    query = parse_qs(urlsplit(url).query)
    assert query == {"key": ["SECRETKEY"], "imgURL": [DIGEST]}


class _Recorder(BaseHTTPRequestHandler):
    seen: list[str] = []
    status = 200

    def do_POST(self) -> None:
        type(self).seen.append(self.path)
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def hook_server() -> Iterator[str]:
    _Recorder.seen = []
    _Recorder.status = 200
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_every_service_gets_the_same_digest_and_a_failure_fails_the_deploy(
    hook_server: str,
) -> None:
    hooks = {
        "web": hook_server + "/deploy/srv-1?key=k1",
        "cron": hook_server + "/deploy/srv-2?key=k2",
    }
    assert deploy_tools.trigger(hooks, DIGEST) == {"web": 200, "cron": 200}
    assert len(_Recorder.seen) == 2
    assert all(parse_qs(urlsplit(p).query)["imgURL"] == [DIGEST] for p in _Recorder.seen)

    _Recorder.status = 500
    with pytest.raises(deploy_tools.DeployError, match="web, cron"):
        deploy_tools.trigger(hooks, DIGEST)


def test_the_cli_output_never_contains_a_hook_url_or_its_key(
    hook_server: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The CLI insists on Render's host, so call the pieces it prints from.
    hooks = {"web": hook_server + "/deploy/srv-1?key=TOPSECRET"}
    for service, status in deploy_tools.trigger(hooks, DIGEST).items():
        print(f"{service}: deploy hook answered {status}")
    monkeypatch.setenv(
        deploy_tools.HOOKS_ENV, json.dumps({"web": "http://example.com/x?key=TOPSECRET"})
    )
    code = deploy_tools.main(["trigger", "--image", DIGEST, "--services", "web"])
    out = capsys.readouterr()
    assert code == 1
    assert "TOPSECRET" not in out.out + out.err
    assert "example.com" not in out.out + out.err
