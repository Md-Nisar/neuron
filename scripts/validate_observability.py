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
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import time
import urllib.error
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
    # SHA-256 of the extracted binary, so a binary already on disk is trusted only if it matches.
    binary_sha256: str


PROMTOOL = Pin(
    binary="promtool",
    version="3.5.0",
    url=(
        "https://github.com/prometheus/prometheus/releases/download/v3.5.0/"
        "prometheus-3.5.0.linux-amd64.tar.gz"
    ),
    sha256="e811827af26d822afb09a4f28314f61b618b12cff5369835a67f674d8b46f39a",
    member="prometheus-3.5.0.linux-amd64/promtool",
    binary_sha256="e59210d5474e2c811a4460fb1593d708b94d58107ae62e9d44e88029bb7e5805",
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
    binary_sha256="9ebbf92fd2b7e754971d32cfd893d85836b2b48e3c2a7c336b5cde2afcad9963",
)
PINS = (PROMTOOL, OTELCOL)

# Largest archive downloaded (the pinned ones are 80 and 121 MB) and largest binary extracted.
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
MAX_BINARY_BYTES = 500 * 1024 * 1024


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
        target = _extract(archive, pin.member, bin_dir / pin.binary)
    if _sha256_file(target) != pin.binary_sha256:
        target.unlink()
        raise ChecksumError(f"{pin.binary}: extracted binary does not match its pinned sha256")
    return target


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            sha.update(chunk)
    return sha.hexdigest()


def cached_binary(pin: Pin, bin_dir: Path) -> Path | None:
    """A binary already in `bin_dir`, only if it is a regular file with the pinned hash."""
    path = bin_dir / pin.binary
    if path.is_symlink() or not path.is_file():
        return None
    return path if _sha256_file(path) == pin.binary_sha256 else None


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects (GitHub serves release assets from another host) but only over https."""

    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
        if not newurl.startswith("https://"):
            raise urllib.error.URLError(f"refusing redirect to a non-https URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, destination: Path) -> str:
    if not url.startswith("https://"):
        raise ValueError("only https downloads are allowed")
    sha = hashlib.sha256()
    request = urllib.request.Request(  # noqa: S310  # nosec B310
        url, headers={"User-Agent": "neuron-validate-observability"}
    )
    opener = urllib.request.build_opener(_HttpsOnlyRedirects)
    total = 0
    with opener.open(request, timeout=120) as response:  # nosec B310
        with destination.open("wb") as out:
            while chunk := response.read(1 << 20):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError(f"download exceeds {MAX_ARCHIVE_BYTES} bytes")
                sha.update(chunk)
                out.write(chunk)
    return sha.hexdigest()


def _extract(archive: Path, member: str, target: Path) -> Path:
    """Write the one named regular-file member to `target`; the archive's paths are never used.

    The bytes go to a new, exclusively created temporary file next to `target` (never opened
    through a symlink) and replace `target` atomically, so a planted symlink or file at `target`
    is replaced, not written through.
    """
    with tarfile.open(archive, "r:gz") as tar:
        info = tar.getmember(member)
        if not info.isreg():
            raise ValueError(f"{member} is not a regular file")
        if info.size > MAX_BINARY_BYTES:
            raise ValueError(f"{member} is larger than {MAX_BINARY_BYTES} bytes")
        source = tar.extractfile(info)
        if source is None:
            raise ValueError(f"{member} is not a regular file")
        temporary = target.with_name(f".{target.name}.{os.urandom(6).hex()}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(temporary, flags, 0o700)  # owner only
            with source, os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(source, out)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
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
        path = cached_binary(pin, bin_dir)
        if path is None:  # absent, a symlink, or not the pinned binary: never trusted
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
