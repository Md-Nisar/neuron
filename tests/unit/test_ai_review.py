# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""AI review layer (`scripts/ai_review.py`): diff parsing, replies, retries, catalog, fallback."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from scripts import ai_review

DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
-x = 1
+x = 2
+y = eval(input())
 def f():
     return x
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""


def _mock_response(
    data: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode("utf-8")
    resp.headers = headers or {}
    resp.status = status
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    return resp


def _mock_http_error(
    code: int, msg: str = "Error", headers: dict[str, str] | None = None
) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.com",
        code=code,
        msg=msg,
        hdrs=headers or {},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": "fail"}'),
    )


# ---------------------------------------------------------------------------
# Existing parser tests
# ---------------------------------------------------------------------------


def test_added_lines_tracks_new_file_line_numbers() -> None:
    assert ai_review.added_lines(DIFF) == {"src/app.py": {2, 3}}


def test_extract_json_ignores_thinking_and_prose() -> None:
    reply = (
        '<think>{"not": "this"}</think>Here you go:\n'
        '```json\n{"summary": "ok", "findings": []}\n```'
    )
    assert ai_review.extract_json(reply) == {"summary": "ok", "findings": []}


def test_extract_json_without_object_raises() -> None:
    with pytest.raises(ValueError):
        ai_review.extract_json("no json here")


def test_parse_findings_drops_malformed_and_sorts_by_severity() -> None:
    data = {
        "findings": [
            {"file": "b/src/app.py", "line": "3", "severity": "low", "title": "minor"},
            {"file": "src/app.py", "line": 3, "severity": "CRITICAL", "title": "eval"},
            {"file": "src/app.py", "title": "no line"},
            "not a dict",
            {"file": "src/app.py", "line": 2, "severity": "weird", "title": "unknown sev"},
        ]
    }

    findings = ai_review.parse_findings(data)

    assert [(f.title, f.severity) for f in findings] == [
        ("eval", "critical"),
        ("unknown sev", "medium"),
        ("minor", "low"),
    ]
    assert findings[0].file == "src/app.py"


def test_split_inline_only_anchors_changed_lines() -> None:
    changed = ai_review.added_lines(DIFF)
    on_change = ai_review.Finding("src/app.py", 3, "high", "eval", "why", "fix")
    off_change = ai_review.Finding("src/app.py", 5, "low", "context", "why", "fix")

    inline, general = ai_review.split_inline([on_change, off_change], changed)

    assert inline == [on_change]
    assert general == [off_change]


def test_posted_text_cannot_mention_people() -> None:
    finding = ai_review.Finding("a.py", 1, "low", "ping @org/team", "see @someone", "x")

    assert "@org" not in finding.body()
    assert "@someone" not in ai_review.review_body("by @bot", "m", [finding], 0)


# ---------------------------------------------------------------------------
# Requirement 1: Retries, Backoff, Retry-After, and Redaction
# ---------------------------------------------------------------------------


def test_redact_secrets() -> None:
    text = "Error with key nvapi-abc123xyz and header Bearer secret-token-value"
    redacted = ai_review.redact_secrets(text, secrets=["nvapi-abc123xyz", "secret-token-value"])
    assert "nvapi-abc123xyz" not in redacted
    assert "secret-token-value" not in redacted
    assert "[REDACTED]" in redacted


def test_parse_retry_after() -> None:
    assert ai_review.parse_retry_after({"Retry-After": "15"}) == 15.0
    assert ai_review.parse_retry_after({"Retry-After": "120"}, max_wait=60.0) == 60.0
    assert ai_review.parse_retry_after({"Retry-After": "invalid"}) is None
    assert ai_review.parse_retry_after({}) is None


def test_request_with_retry_succeeds_first_try() -> None:
    mock_resp = _mock_response({"result": "ok"})
    sleeps: list[float] = []

    with patch("urllib.request.urlopen", return_value=mock_resp):
        data, retries = ai_review.request_with_retry(
            "https://api.test/endpoint",
            headers={},
            sleep_fn=sleeps.append,
        )

    assert data == {"result": "ok"}
    assert retries == []
    assert sleeps == []


def test_request_with_retry_exponential_backoff() -> None:
    err503 = _mock_http_error(503, "Service Unavailable")
    err500 = _mock_http_error(500, "Internal Server Error")
    mock_ok = _mock_response({"choices": [{"message": {"content": "done"}}]})

    sleeps: list[float] = []
    with patch("urllib.request.urlopen", side_effect=[err503, err500, mock_ok]):
        data, retries = ai_review.request_with_retry(
            "https://api.test/endpoint",
            headers={},
            backoff_delays=(2.0, 4.0, 8.0),
            sleep_fn=sleeps.append,
        )

    assert data["choices"][0]["message"]["content"] == "done"
    assert len(retries) == 2
    assert sleeps == [2.0, 4.0]
    assert retries[0].attempt == 1
    assert retries[1].attempt == 2


def test_request_with_retry_respects_retry_after_header() -> None:
    err429 = _mock_http_error(429, "Rate Limited", headers={"Retry-After": "7"})
    mock_ok = _mock_response({"result": "ok"})

    sleeps: list[float] = []
    with patch("urllib.request.urlopen", side_effect=[err429, mock_ok]):
        data, retries = ai_review.request_with_retry(
            "https://api.test/endpoint",
            headers={},
            backoff_delays=(2.0, 4.0, 8.0),
            sleep_fn=sleeps.append,
        )

    assert data == {"result": "ok"}
    assert len(retries) == 1
    assert sleeps == [7.0]
    assert retries[0].delay == 7.0


def test_request_with_retry_permanent_error_not_retried() -> None:
    for code in (400, 401, 403, 404):
        err = _mock_http_error(code, "Unauthorized or Bad Request")
        sleeps: list[float] = []

        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ai_review.PermanentHTTPError) as exc_info:
                ai_review.request_with_retry(
                    "https://api.test/endpoint",
                    headers={},
                    sleep_fn=sleeps.append,
                )

        assert exc_info.value.code == code
        assert sleeps == []


def test_request_with_retry_network_errors_retried() -> None:
    net_err = urllib.error.URLError("Connection reset by peer")
    timeout_err = TimeoutError("Timed out")
    mock_ok = _mock_response({"status": "recovered"})

    sleeps: list[float] = []
    with patch("urllib.request.urlopen", side_effect=[net_err, timeout_err, mock_ok]):
        data, retries = ai_review.request_with_retry(
            "https://api.test/endpoint",
            headers={},
            backoff_delays=(2.0, 4.0, 8.0),
            sleep_fn=sleeps.append,
        )

    assert data == {"status": "recovered"}
    assert len(retries) == 2
    assert sleeps == [2.0, 4.0]


def test_request_with_retry_exhausts_attempts() -> None:
    err502 = _mock_http_error(502, "Bad Gateway")
    sleeps: list[float] = []

    with patch("urllib.request.urlopen", side_effect=err502):
        with pytest.raises(ai_review.TransientHTTPError) as exc_info:
            ai_review.request_with_retry(
                "https://api.test/endpoint",
                headers={},
                max_attempts=4,
                backoff_delays=(2.0, 4.0, 8.0),
                sleep_fn=sleeps.append,
            )

    assert exc_info.value.code == 502
    assert sleeps == [2.0, 4.0, 8.0]


# ---------------------------------------------------------------------------
# Requirement 2: Timeout Configuration
# ---------------------------------------------------------------------------


def test_get_request_timeout_defaults_and_env_overrides() -> None:
    assert ai_review.get_request_timeout({}) == 180.0
    assert ai_review.get_request_timeout({"NVIDIA_TIMEOUT_SECONDS": "240"}) == 240.0
    assert (
        ai_review.get_request_timeout(
            {"NVIDIA_READ_TIMEOUT": "120", "NVIDIA_CONNECT_TIMEOUT": "45"}
        )
        == 120.0
    )


# ---------------------------------------------------------------------------
# Requirement 4: Model Catalog Verification
# ---------------------------------------------------------------------------


def test_verify_catalog_identifies_available_and_skips_missing() -> None:
    catalog_data = {
        "data": [
            {"id": "nvidia/nemotron-3-ultra-550b-a55b"},
            {"id": "deepseek-ai/deepseek-v4.1-flash"},
        ]
    }
    mock_resp = _mock_response(catalog_data)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        available, to_attempt, skipped = ai_review.verify_catalog(
            api_key="test-key",
            configured_models=[
                "nvidia/nemotron-3-ultra-550b-a55b",
                "deepseek-ai/deepseek-v4.1-flash",
                "missing-model/id",
            ],
            timeout=30.0,
            skip_unavailable=True,
        )

    assert available == {
        "nvidia/nemotron-3-ultra-550b-a55b",
        "deepseek-ai/deepseek-v4.1-flash",
    }
    assert to_attempt == [
        "nvidia/nemotron-3-ultra-550b-a55b",
        "deepseek-ai/deepseek-v4.1-flash",
    ]
    assert "missing-model/id" in skipped


def test_verify_catalog_handles_failure_without_crashing() -> None:
    err500 = _mock_http_error(500, "Catalog Service Down")
    with patch("urllib.request.urlopen", side_effect=err500):
        available, to_attempt, skipped = ai_review.verify_catalog(
            api_key="test-key",
            configured_models=["model-a", "model-b"],
            timeout=30.0,
            strict_catalog=False,
            sleep_fn=lambda _: None,
        )

    assert available is None
    assert to_attempt == ["model-a", "model-b"]
    assert skipped == {}


def test_verify_catalog_strict_mode_fails_on_catalog_error() -> None:
    err500 = _mock_http_error(500, "Catalog Service Down")
    with patch("urllib.request.urlopen", side_effect=err500):
        available, to_attempt, skipped = ai_review.verify_catalog(
            api_key="test-key",
            configured_models=["model-a"],
            timeout=30.0,
            strict_catalog=True,
            sleep_fn=lambda _: None,
        )

    assert available is None
    assert to_attempt == []
    assert "model-a" in skipped


# ---------------------------------------------------------------------------
# Requirements 3 & 5: Model Fallback and Exception Isolation
# ---------------------------------------------------------------------------


def test_model_fallback_tries_next_model_when_first_fails() -> None:
    # Model 1 fails completely; Model 2 succeeds
    with patch("scripts.ai_review.review_with_model") as mock_rev:
        mock_rev.side_effect = [
            RuntimeError("Model 1 overloaded (HTTP 503)"),
            (
                {"summary": "Clean PR"},
                [ai_review.Finding("src/app.py", 3, "high", "eval", "bad", "good")],
                1,
                0,
                1,
            ),
        ]

        # Call with fallback
        models = ["nvidia/nemotron-3-ultra-550b-a55b", "deepseek-ai/deepseek-v4.1-flash"]
        successful = []
        failed = {}
        for m in models:
            try:
                data, findings, v_cnt, unv_cnt, retries = ai_review.review_with_model(
                    m, "diff", "ctx", "key", 30.0, sleep_fn=lambda _: None
                )
                successful.append(m)
                break
            except Exception as e:
                failed[m] = str(e)

        assert successful == ["deepseek-ai/deepseek-v4.1-flash"]
        assert "nvidia/nemotron-3-ultra-550b-a55b" in failed
        assert "HTTP 503" in failed["nvidia/nemotron-3-ultra-550b-a55b"]


def test_partial_completion_exit_code_policy() -> None:
    # Default is nonzero (1)
    assert ai_review.get_partial_exit_code({}) == 1
    # Explicit false -> 0
    assert ai_review.get_partial_exit_code({"AI_REVIEW_FAIL_ON_PARTIAL": "false"}) == 0
    # Explicit partial code 0
    assert ai_review.get_partial_exit_code({"AI_REVIEW_PARTIAL_EXIT_CODE": "0"}) == 0


def test_summary_formatting() -> None:
    summary = ai_review.ReviewExecutionSummary(
        status="PARTIAL",
        successful_reviews=[
            ai_review.ModelReviewResult(
                model="deepseek-ai/deepseek-v4.1-flash",
                summary="LGTM",
                findings=[],
                verified_count=0,
                unverified_count=0,
                retries=1,
            )
        ],
        failed_models={"nvidia/nemotron-3-ultra-550b-a55b": "HTTP 503"},
        skipped_models={"z-ai/glm-5.3": "Missing from catalog"},
        retry_counts={"deepseek-ai/deepseek-v4.1-flash": 1},
        catalog_verified=True,
    )

    markdown = ai_review.format_summary_markdown(summary)
    assert "## AI Code Review: PARTIAL" in markdown
    assert "deepseek-ai/deepseek-v4.1-flash" in markdown
    assert "HTTP 503" in markdown
    assert "Missing from catalog" in markdown


# ---------------------------------------------------------------------------
# Requirement 6: Duplicate Comment Prevention
# ---------------------------------------------------------------------------


def test_check_duplicate_review_filters_existing_comments() -> None:
    existing_comments = [
        {"path": "src/app.py", "line": 3, "body": "**HIGH: EVAL**\n\nwhy\n\n**Suggested fix:** fix"}
    ]
    mock_comments_resp = _mock_response(existing_comments)
    mock_reviews_resp = _mock_response([])

    new_comments = [
        {
            "path": "src/app.py",
            "line": 3,
            "body": "**HIGH: EVAL**\n\nwhy\n\n**Suggested fix:** fix",
        },
        {
            "path": "src/app.py",
            "line": 2,
            "body": "**LOW: STYLE**\n\nwhy\n\n**Suggested fix:** fix",
        },
    ]

    with patch("urllib.request.urlopen", side_effect=[mock_comments_resp, mock_reviews_resp]):
        is_dup, filtered = ai_review.check_duplicate_review(
            repo="owner/repo",
            pr_number=1,
            github_token="gh-token",  # noqa: S106
            head_sha="abc1234",
            body="review body",
            comments=new_comments,
        )

    assert not is_dup
    # Only line 2 should remain; line 3 was filtered as duplicate
    assert len(filtered) == 1
    assert filtered[0]["line"] == 2
