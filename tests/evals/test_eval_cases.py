from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import pytest

from neuron_agent.evaluation import (
    CASE_FLAGS,
    EVAL_CATEGORIES,
    MULTI_TURN_CASES,
    MULTI_TURN_EVAL_CATEGORIES,
    SECURITY_CASES,
    SECURITY_EVAL_CATEGORIES,
    SINGLE_TURN_CASES,
    SYSTEM_PROMPT_MARKERS,
    TRAJECTORY_MODES,
    load_dataset_version,
    load_eval_cases,
)

pytestmark = pytest.mark.eval

V4_CATEGORIES = {
    "direct_injection_tools",
    "system_prompt_disclosure",
    "cross_turn_injection",
    "tool_shaped_injection",
    "scope_escalation",
}
_ALLOWED_V4_FIELDS = {
    "id",
    "category",
    "victim_setup",
    "setup",
    "input",
    "expected_behavior",
    "expected_tools",
    "expected_keywords",
    "forbidden_keywords",
    "forbid_system_prompt_markers",
    "attacker_permissions",
    "grading_note",
}

_REQUIRED_FIELDS = {
    "id",
    "input",
    "expected_behavior",
    "category",
    "expected_tools",
    "expected_keywords",
}


def test_eval_cases_have_required_fields() -> None:
    cases = load_eval_cases(Path("tests/fixtures/eval_cases.json"))
    assert cases
    for case in cases:
        assert set(case) >= _REQUIRED_FIELDS
        assert isinstance(case["expected_tools"], list)
        assert isinstance(case["expected_keywords"], list)


def test_eval_cases_cover_every_required_category() -> None:
    cases = load_eval_cases(Path("tests/fixtures/eval_cases.json"))
    categories = {case["category"] for case in cases}
    assert categories == EVAL_CATEGORIES


def test_eval_case_ids_are_unique() -> None:
    cases = load_eval_cases(Path("tests/fixtures/eval_cases.json"))
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_multi_turn_cases_have_required_fields() -> None:
    cases = load_eval_cases(MULTI_TURN_CASES)
    assert len(cases) >= 10
    for case in cases:
        assert set(case) >= _REQUIRED_FIELDS | {"setup"}
        setup = case["setup"]
        assert isinstance(setup, list) and setup, f"{case['id']} needs earlier turns"
        assert all(isinstance(turn, str) and turn for turn in setup)


def test_multi_turn_cases_cover_every_required_category() -> None:
    categories = {case["category"] for case in load_eval_cases(MULTI_TURN_CASES)}
    assert categories == MULTI_TURN_EVAL_CATEGORIES


def test_eval_case_ids_are_unique_across_datasets() -> None:
    ids = [
        case["id"]
        for path in (SINGLE_TURN_CASES, MULTI_TURN_CASES, SECURITY_CASES)
        for case in load_eval_cases(path)
    ]
    assert len(ids) == len(set(ids))


def test_security_cases_have_required_fields() -> None:
    cases = load_eval_cases(SECURITY_CASES)
    assert len(cases) >= 10
    for case in cases:
        assert set(case) >= _REQUIRED_FIELDS | {"victim_setup", "forbidden_keywords"}
        victim_setup = case["victim_setup"]
        assert isinstance(victim_setup, list) and victim_setup, case["id"]
        # Every case must be able to detect a leak, and no case may expect a tool call.
        forbidden = case["forbidden_keywords"]
        assert isinstance(forbidden, list) and forbidden, case["id"]
        assert all(any(kw in turn for turn in victim_setup) for kw in forbidden), case["id"]
        assert case["expected_tools"] == [], case["id"]
        assert not any(kw in str(case["input"]) for kw in forbidden), case["id"]


def test_security_v4_cases_assert_invariants_and_explain_themselves() -> None:
    v4 = [c for c in load_eval_cases(SECURITY_CASES) if "4.0.0" in str(c.get("grading_note"))]
    assert len(v4) >= 12
    assert {c["category"] for c in v4} == V4_CATEGORIES
    for case in v4:
        # State and invariants only: no wording expectations, no judge.
        assert case["expected_keywords"] == [], case["id"]
        assert not case.get("expected_flags"), case["id"]
        assert "expected_number" not in case, case["id"]
        assert set(case) <= _ALLOWED_V4_FIELDS, case["id"]
        assert "4.0.0" in str(case["grading_note"]), case["id"]
        if case["category"] == "system_prompt_disclosure":
            assert case.get("forbid_system_prompt_markers") is True, case["id"]
        if case["category"] == "scope_escalation":
            assert "attacker_permissions" in case, case["id"]
        assert not any(m in str(case["input"]).lower() for m in SYSTEM_PROMPT_MARKERS), case["id"]


def test_security_cases_cover_every_required_category() -> None:
    cases = load_eval_cases(SECURITY_CASES)
    assert {case["category"] for case in cases} == SECURITY_EVAL_CATEGORIES
    for case in cases:
        aims_at_victim_thread = case.get("target") == "victim_thread"
        assert aims_at_victim_thread == (case["category"] == "cross_user_thread_access")
        if case["category"] == "cross_user_thread_id":
            assert "{victim_thread_id}" in str(case["input"]), case["id"]
    assert any("setup" in case for case in cases), "dataset v3 needs multi-turn attackers"


def test_every_dataset_declares_a_version() -> None:
    for path in (SINGLE_TURN_CASES, MULTI_TURN_CASES, SECURITY_CASES):
        assert re.fullmatch(r"\d+\.\d+\.\d+", load_dataset_version(path)), path


def test_structured_expectations_are_well_formed_and_explained() -> None:
    for path in (SINGLE_TURN_CASES, MULTI_TURN_CASES, SECURITY_CASES):
        for case in load_eval_cases(path):
            assert case.get("trajectory", "unordered") in TRAJECTORY_MODES, case["id"]
            flags = cast("list[str]", case.get("expected_flags", []))
            assert set(flags) <= CASE_FLAGS, case["id"]
            number = cast("dict[str, float] | None", case.get("expected_number"))
            if number is not None:
                assert set(number) <= {"value", "tolerance"}, case["id"]
                assert isinstance(number["value"], int | float), case["id"]
            if flags or number is not None or "trajectory" in case:
                assert case.get("grading_note"), f"{case['id']} must record why it was changed"
