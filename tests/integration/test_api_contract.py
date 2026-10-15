from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_integration_placeholder_documents_external_credentials() -> None:
    pytest.skip(
        "Live model/API integration requires a provider key and is documented in EVALUATION.md."
    )
