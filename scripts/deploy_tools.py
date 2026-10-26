# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Decisions and Render calls for the deploy workflow (#151, ADR 0008 decision 6).

The workflow (`.github/workflows/deploy.yml`) calls three subcommands:

    check-release  --tag v1.2.3            the tag matches pyproject.toml and CHANGELOG.md
    check-image    --image REF             REF is `ghcr.io/md-nisar/neuron@sha256:<64 hex>`
    trigger        --image REF --services a,b
                                           POST each service's deploy hook with that image

Render facts are assumed (ADR 0008, "Implementation note: render.yaml assumptions"): a deploy
hook is `https://api.render.com/deploy/srv-...?key=...`, accepts `imgURL` to deploy a given
image on an image-backed service, and answers 2xx when the deploy was queued. The hooks are
read from the `DEPLOY_HOOKS` environment variable (a JSON object, service name -> URL), which
the workflow takes from the Environment's secret. A hook URL carries its key, so it is never
printed: output names the service and the HTTP status only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path

try:
    from changelog_section import extract_section
except ImportError:  # imported as `scripts.deploy_tools`, as the tests do
    from scripts.changelog_section import extract_section

HOOKS_ENV = "DEPLOY_HOOKS"
IMAGE_PATTERN = re.compile(r"^ghcr\.io/md-nisar/neuron@sha256:[0-9a-f]{64}$")
TAG_PATTERN = re.compile(r"^v(\d+\.\d+\.\d+)$")
_HOOK_HOST = "api.render.com"
_ROOT = Path(__file__).resolve().parents[1]


class DeployError(Exception):
    """A refused or failed step. The message never contains a hook URL."""


def check_image(image: str) -> None:
    """Accept only a digest reference: a tag is mutable, so it never deploys."""
    if not IMAGE_PATTERN.fullmatch(image):
        raise DeployError("image must be ghcr.io/md-nisar/neuron@sha256:<64 hex digits>")


def check_release(tag: str, pyproject_text: str, changelog_text: str) -> str:
    """Return the version when `tag` is `vX.Y.Z`, equals `pyproject.toml` and has a section."""
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise DeployError("tag must look like v1.2.3")
    version = match.group(1)
    declared = tomllib.loads(pyproject_text)["project"]["version"]
    if declared != version:
        raise DeployError(f"tag {tag} differs from pyproject.toml version {declared}")
    if extract_section(changelog_text, version) is None:
        raise DeployError(f"CHANGELOG.md has no section for {version}")
    return version


def select_hooks(raw: str | None, services: list[str]) -> dict[str, str]:
    """Return the hook URL of every requested service; refuse a missing or foreign one.

    Every service of an environment is deployed together with the same image, so a service
    without a hook (or a hook that is not Render's) stops the whole deploy before any call.
    """
    if not raw:
        raise DeployError(f"{HOOKS_ENV} is not set")
    try:
        hooks = json.loads(raw)
    except json.JSONDecodeError:
        raise DeployError(f"{HOOKS_ENV} is not valid JSON") from None
    if not isinstance(hooks, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in hooks.items()
    ):
        raise DeployError(f"{HOOKS_ENV} must be an object of service name to URL")
    if not services:
        raise DeployError("no services requested")
    missing = [s for s in services if s not in hooks]
    if missing:
        raise DeployError(f"no deploy hook for: {', '.join(missing)}")
    for service in services:
        parts = urllib.parse.urlsplit(hooks[service])
        if parts.scheme != "https" or parts.hostname != _HOOK_HOST:
            raise DeployError(f"the hook for {service} is not an https://{_HOOK_HOST} URL")
    return {service: hooks[service] for service in services}


def hook_request_url(hook: str, image: str) -> str:
    """Add the image to the hook as `imgURL`, keeping the hook's own query (its key)."""
    parts = urllib.parse.urlsplit(hook)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "imgURL"]
    query.append(("imgURL", image))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def trigger(hooks: Mapping[str, str], image: str, timeout: float = 30.0) -> dict[str, int]:
    """POST every hook with the same image; return service -> status. Raises if any failed."""
    statuses: dict[str, int] = {}
    for service, hook in hooks.items():
        request = urllib.request.Request(  # noqa: S310  # nosec B310 - https checked above
            hook_request_url(hook, image), method="POST"
        )
        try:
            with _opener.open(request, timeout=timeout) as response:
                statuses[service] = response.status
        except urllib.error.HTTPError as exc:
            statuses[service] = exc.code
        except (urllib.error.URLError, TimeoutError):
            statuses[service] = 0
    failed = [s for s, code in statuses.items() if not 200 <= code < 300]
    if failed:
        raise DeployError(f"deploy hook failed for: {', '.join(failed)}")
    return statuses


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    release = sub.add_parser("check-release")
    release.add_argument("--tag", required=True)
    image = sub.add_parser("check-image")
    image.add_argument("--image", required=True)
    deploy = sub.add_parser("trigger")
    deploy.add_argument("--image", required=True)
    deploy.add_argument("--services", required=True, help="comma-separated service names")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-release":
            version = check_release(
                args.tag,
                (_ROOT / "pyproject.toml").read_text("utf-8"),
                (_ROOT / "CHANGELOG.md").read_text("utf-8"),
            )
            print(f"release {version}: pyproject.toml and CHANGELOG.md agree")
        elif args.command == "check-image":
            check_image(args.image)
            print("image reference is a digest")
        else:
            check_image(args.image)
            services = [s.strip() for s in args.services.split(",") if s.strip()]
            hooks = select_hooks(os.environ.get(HOOKS_ENV), services)
            for service, status in trigger(hooks, args.image).items():
                print(f"{service}: deploy hook answered {status}")
    except DeployError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
