# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A live key given to a test must not show in the failure report pytest prints for it."""

from __future__ import annotations

from pydantic import SecretStr
from tests.conftest import MaskedSecret

_KEY = "nvapi-" + "x" * 24


def test_the_masked_key_has_no_visible_repr_but_is_still_the_key() -> None:
    key = MaskedSecret(_KEY)

    assert _KEY not in repr(key)
    assert _KEY not in f"{key!r}"
    assert key == _KEY
    assert f"Bearer {key}" == f"Bearer {_KEY}"
    assert SecretStr(key).get_secret_value() == _KEY
