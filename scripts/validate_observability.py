#!/usr/bin/env python3
# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Validate the Prometheus rules and the Collector configuration with the real tools (#155).

    python scripts/validate_observability.py check            # download, verify, validate
    python scripts/validate_observability.py reject-broken    # both tools must reject a broken file

`promtool` and `otelcol-contrib` are downloaded from their GitHub releases at the versions
pinned in `PINS`, and each archive is verified against the pinned SHA-256 before anything is
extracted. The pins are Linux amd64 only (the CI runner). To bump one, change the version, the
URL and the hash together, taking the hash from the release's published checksums file
(`sha256sums.txt` for Prometheus, `opentelemetry-collector-releases_otelcol-contrib_checksums.txt`
for the Collector) and from your own `sha256sum` of the download.

Standard library only. No secret is read or needed. Exit status is 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import time
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "deploy" / "observability" / "prometheus-alerts.yaml"
COLLECTOR = ROOT / "deploy" / "observability" / "otel-collector.yaml"
BROKEN_RULES = ROOT / "tests" / "fixtures" / "observability" / "broken-alerts.yaml"
BROKEN_COLLECTOR = ROOT / "tests" / "fixtures" / "observability" / "broken-collector.yaml"

# The Collector config reads this at validation time; any non-empty value passes, none is used.
PLACEHOLDER_ENV = {"OTEL_BACKEND_ENDPOINT": "collector-validate.invalid:4317"}


@dataclass(frozen=True)
class Pin:
    """One release asset: the archive's URL and SHA-256, and the binary inside it."""

    binary: str
    version: str
    url: str
    sha256: str
    member: str


PROMTOOL = Pin(
    binary="promtool",
    version="3.5.0",
    url=(
        "https://github.com/prometheus/prometheus/releases/download/v3.5.0/"
        "prometheus-3.5.0.linux-amd64.tar.gz"
    ),
    sha256="e811827af26d822afb09a4f28314f61b618b12cff5369835a67f674d8b46f39a",
    member="prometheus-3.5.0.linux-amd64/promtool",
)
OTELCOL = Pin(
    binary="otelcol-contrib",
    version="0.120.0",
    url=(
        "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/"
        "v0.120.0/otelcol-contrib_0.120.0_linux_amd64.tar.gz"
    ),
    sha256="81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb",
    member="otelcol-contrib",
)
PINS = (PROMTOOL, OTELCOL)


class ChecksumError(Exception):
    """A downloaded archive does not match its pinned SHA-256."""


def fetch(pin: Pin, bin_dir: Path, *, attempts: int = 3) -> Path:
    """Download `pin`, verify its SHA-256, and extract only its binary into `bin_dir`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "archive.tar.gz"
        for attempt in range(1, attempts + 1):
            try:
                digest = _download(pin.url, archive)
                break
            except OSError as exc:
                if attempt == attempts:
                    raise
                print(f"download of {pin.url} failed ({exc}); retrying", file=sys.stderr)
                time.sleep(2 * attempt)
        if digest != pin.sha256:
            raise ChecksumError(f"{pin.binary}: sha256 {digest} != pinned {pin.sha256}")
        return _extract(archive, pin.member, bin_dir / pin.binary)


def _download(url: str, destination: Path) -> str:
    if not url.startswith("https://"):
        raise ValueError("only https downloads are allowed")
    sha = hashlib.sha256()
    request = urllib.request.Request(  # noqa: S310  # nosec B310
        url, headers={"User-Agent": "neuron-validate-observability"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310  # nosec B310
        with destination.open("wb") as out:
            while chunk := response.read(1 << 20):
                sha.update(chunk)
                out.write(chunk)
    return sha.hexdigest()


def _extract(archive: Path, member: str, target: Path) -> Path:
    """Write the one named member to `target`; the archive's own paths are never used."""
    with tarfile.open(archive, "r:gz") as tar:
        info = tar.getmember(member)
        source = tar.extractfile(info)
        if source is None:
            raise ValueError(f"{member} is not a regular file")
        with source, target.open("wb") as out:
            shutil.copyfileobj(source, out)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return target


def promtool_command(promtool: Path, rules: Path) -> list[str]:
    return [str(promtool), "check", "rules", str(rules)]


def otelcol_command(otelcol: Path, config: Path) -> list[str]:
    return [str(otelcol), "validate", f"--config={config}"]


def run(command: Sequence[str]) -> bool:
    """Run one validator, show its output, and return whether it exited 0."""
    env = {**PLACEHOLDER_ENV, **os.environ}
    # Fixed argument lists, no shell; the executables are the verified ones from `fetch`.
    result = subprocess.run(  # noqa: S603  # nosec B603
        list(command), capture_output=True, text=True, env=env, check=False, timeout=300
    )
    print(f"$ {' '.join(command)}")
    for stream in (result.stdout, result.stderr):
        if stream.strip():
            print(stream.rstrip())
    print(f"exit status {result.returncode}")
    return result.returncode == 0


def check(promtool: Path, otelcol: Path, rules: Path, collector: Path) -> bool:
    """Both validators run, so one failure never hides the other."""
    rules_ok = run(promtool_command(promtool, rules))
    collector_ok = run(otelcol_command(otelcol, collector))
    return rules_ok and collector_ok


def reject_broken(promtool: Path, otelcol: Path) -> bool:
    """Each tool must reject its broken fixture and still accept the real file."""
    outcomes = {
        "promtool rejects the broken rules": not run(promtool_command(promtool, BROKEN_RULES)),
        "otelcol-contrib rejects the broken config": not run(
            otelcol_command(otelcol, BROKEN_COLLECTOR)
        ),
        "promtool accepts the real rules": run(promtool_command(promtool, RULES)),
        "otelcol-contrib accepts the real config": run(otelcol_command(otelcol, COLLECTOR)),
    }
    for name, passed in outcomes.items():
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    return all(outcomes.values())


def _binaries(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.promtool and args.otelcol:
        return args.promtool, args.otelcol
    bin_dir: Path = args.bin_dir or Path(tempfile.mkdtemp(prefix="neuron-observability-"))
    found = []
    for pin in PINS:
        path = bin_dir / pin.binary
        if not path.exists():
            path = fetch(pin, bin_dir)
            print(f"fetched {pin.binary} {pin.version} (sha256 {pin.sha256} verified)")
        found.append(path)
    return found[0], found[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("command", choices=("check", "reject-broken"))
    parser.add_argument("--bin-dir", type=Path, help="where to download to / find the binaries")
    parser.add_argument("--promtool", type=Path, help="use this promtool instead of downloading")
    parser.add_argument("--otelcol", type=Path, help="use this otelcol-contrib instead")
    parser.add_argument("--rules", type=Path, default=RULES)
    parser.add_argument("--collector", type=Path, default=COLLECTOR)
    args = parser.parse_args(argv)
    try:
        promtool, otelcol = _binaries(args)
    except (ChecksumError, OSError, ValueError, tarfile.TarError, KeyError) as exc:
        print(f"cannot obtain the validators: {exc}", file=sys.stderr)
        return 2
    if args.command == "check":
        ok = check(promtool, otelcol, args.rules, args.collector)
    else:
        ok = reject_broken(promtool, otelcol)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
