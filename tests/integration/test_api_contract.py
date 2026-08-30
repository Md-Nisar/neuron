from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_integration_placeholder_documents_external_credentials() -> None:
    pytest.skip(
        "Live model/API integration requires OPENAI_API_KEY and is documented in EVALUATION.md."
    )
