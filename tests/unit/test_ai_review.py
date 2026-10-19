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
    # Advisory by default (0)
    assert ai_review.get_partial_exit_code({}) == 0
    assert ai_review.get_partial_exit_code({"AI_REVIEW_FAIL_ON_PARTIAL": "true"}) == 1
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


# ---------------------------------------------------------------------------
# Advisory exit codes, time budget, 422 fallback, verified claim
# ---------------------------------------------------------------------------

MODELS = "model-a,model-b"


def _main_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    for key in ("AI_REVIEW_FAIL_ON_ERROR", "AI_REVIEW_DEADLINE_SECONDS", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(key, raising=False)
    env = {
        "NVIDIA_API_KEY": "nvapi-secret",
        "AI_REVIEW_MODELS": MODELS,
        "AI_REVIEW_SKIP_UNAVAILABLE": "false",
        "BASE_SHA": "a" * 40,
        "HEAD_SHA": "b" * 40,
        **extra,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ai_review, "git_diff", lambda base, head: DIFF)


def test_main_all_models_fail_is_advisory_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _main_env(monkeypatch)
    with patch("urllib.request.urlopen", side_effect=_mock_http_error(503)):
        assert ai_review.main(sleep_fn=lambda _: None) == 0
    assert "::warning::No model produced a review" in capsys.readouterr().out


def test_main_all_models_fail_exits_1_when_fail_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _main_env(monkeypatch, AI_REVIEW_FAIL_ON_ERROR="true")
    with patch("urllib.request.urlopen", side_effect=_mock_http_error(503)):
        assert ai_review.main(sleep_fn=lambda _: None) == 1


def test_main_diff_failure_and_missing_shas_are_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    _main_env(monkeypatch)

    def boom(base: str, head: str) -> str:
        raise RuntimeError("git failed")

    monkeypatch.setattr(ai_review, "git_diff", boom)
    assert ai_review.main(sleep_fn=lambda _: None) == 0
    monkeypatch.setenv("AI_REVIEW_FAIL_ON_ERROR", "true")
    assert ai_review.main(sleep_fn=lambda _: None) == 1

    monkeypatch.delenv("AI_REVIEW_FAIL_ON_ERROR")
    monkeypatch.setenv("BASE_SHA", "")
    assert ai_review.main(sleep_fn=lambda _: None) == 0


def test_request_with_retry_stops_when_deadline_passes_during_backoff() -> None:
    sleeps: list[float] = []
    with (
        patch("urllib.request.urlopen", side_effect=_mock_http_error(503)) as mock_open,
        patch("scripts.ai_review.time.monotonic", return_value=100.0),
        pytest.raises(ai_review.TransientHTTPError, match="time budget exhausted"),
    ):
        ai_review.request_with_retry(
            "https://example.com",
            headers={},
            sleep_fn=sleeps.append,
            backoff_delays=(10.0,),
            deadline=106.0,  # the first backoff (10s) would pass it
        )
    assert mock_open.call_count == 1
    assert sleeps == []


def test_request_with_retry_clamps_timeout_to_time_left() -> None:
    with (
        patch("urllib.request.urlopen", return_value=_mock_response({"ok": 1})) as mock_open,
        patch("scripts.ai_review.time.monotonic", return_value=100.0),
    ):
        ai_review.request_with_retry(
            "https://example.com", headers={}, timeout=180.0, deadline=107.0
        )
    assert mock_open.call_args.kwargs["timeout"] == 7.0


def test_request_with_retry_does_not_start_an_attempt_that_cannot_finish() -> None:
    with (
        patch("urllib.request.urlopen") as mock_open,
        patch("scripts.ai_review.time.monotonic", return_value=100.0),
        pytest.raises(ai_review.TransientHTTPError, match="time budget exhausted"),
    ):
        ai_review.request_with_retry(
            "https://example.com", headers={}, timeout=180.0, deadline=102.0
        )
    mock_open.assert_not_called()


def test_main_deadline_exhausted_makes_no_further_attempts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _main_env(monkeypatch, AI_REVIEW_DEADLINE_SECONDS="50")
    clock = iter([0.0] + [1000.0] * 50)  # main() starts at 0, then the budget is long gone
    monkeypatch.setattr(ai_review.time, "monotonic", lambda: next(clock))
    with patch("urllib.request.urlopen") as mock_open:
        assert ai_review.main(sleep_fn=lambda _: None) == 0
    out = capsys.readouterr().out
    mock_open.assert_not_called()
    assert "time budget exhausted" in out
    assert "Model 'model-a' skipped" in out
    assert "Model 'model-b' skipped" in out


def _success_review() -> tuple[dict[str, Any], list[Any], int, int, int]:
    finding = ai_review.Finding("src/app.py", 3, "high", "eval", "bad", "good")
    return {"summary": "Risky."}, [finding], 0, 1, 0


def test_main_422_on_inline_comments_reposts_everything_in_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _main_env(
        monkeypatch,
        GITHUB_REPOSITORY="o/r",
        PR_NUMBER="7",
        GITHUB_TOKEN="x" * 8,
        AI_REVIEW_MODELS="model-a",
    )
    posts: list[dict[str, Any]] = []

    def fake_request(url: str, **kwargs: Any) -> tuple[Any, list[Any]]:
        if url.endswith("/models"):
            return {"data": []}, []
        posts.append(kwargs["payload"])
        if len(posts) == 1:
            raise ai_review.PermanentHTTPError(422, "Unprocessable")
        return {}, []

    monkeypatch.setattr(ai_review, "request_with_retry", fake_request)
    monkeypatch.setattr(ai_review, "review_with_model", lambda *a, **k: _success_review())
    monkeypatch.setattr(ai_review, "check_duplicate_review", lambda *a, **k: (False, a[5]))
    assert ai_review.main(sleep_fn=lambda _: None) == 0
    assert len(posts) == 2
    assert posts[0]["comments"]
    assert posts[1]["comments"] == []
    assert "eval" in posts[1]["body"]
    assert "src/app.py:3" in posts[1]["body"]


def test_review_body_claims_verification_only_when_verified() -> None:
    assert "verified by a second pass" in ai_review.review_body("s", "m", [], 1, verified=True)
    unverified = ai_review.review_body("s", "m", [], 1)
    assert "were verified by a second pass" not in unverified
    assert "not verified" in unverified


def test_review_with_model_reports_unverified_when_verify_pass_fails() -> None:
    review = json.dumps(
        {
            "summary": "s",
            "findings": [
                {"file": "src/app.py", "line": 3, "severity": "high", "title": "t"},
            ],
        }
    )
    calls = iter([(review, []), ai_review.TransientHTTPError(503, "down")])

    def fake_chat(*args: Any, **kwargs: Any) -> tuple[str, list[Any]]:
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    with patch("scripts.ai_review.chat_completion", side_effect=fake_chat):
        _, findings, verified, unverified, _ = ai_review.review_with_model(
            "m", "diff", "ctx", "key", 30.0
        )
    assert (len(findings), verified, unverified) == (1, 0, 1)
