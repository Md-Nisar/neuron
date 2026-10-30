# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Neuron Agent application package."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    # `pyproject.toml` is the only hand-edited version.
    __version__ = version("neuron-agent")
except PackageNotFoundError:  # pragma: no cover - source tree that was never installed
    __version__ = "0+unknown"
