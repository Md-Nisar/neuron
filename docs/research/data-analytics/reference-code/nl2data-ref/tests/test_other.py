import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from nl2data_ref.answer_checks import faithful, results_match
from nl2data_ref.governance import (ScopedValueIndex, ValueEntry, choose_threshold,
                                    redact_trace, scope_key)
from nl2data_ref.metrics import Filter, MetricRequest, SemanticModel, to_metricflow_where, validate_request

MODEL = SemanticModel(metrics={"net_revenue"},
                      dimensions={"region": "categorical", "metric_time__fiscal_quarter": "time"})


# ---- typed Tier 1 filters ----
def test_free_text_filter_rejected_by_schema():
    with pytest.raises(ValidationError):
        MetricRequest.model_validate({"metrics": ["net_revenue"],
                                      "filters": [{"dimension": "region) OR 1=1 --", "op": "=", "values": ["x"]}]})


def test_unknown_operator_rejected():
    with pytest.raises(ValidationError):
        Filter.model_validate({"dimension": "region", "op": "LIKE", "values": ["%"]})


def test_value_quote_escaped():
    f = Filter(dimension="region", op="=", values=["O'Brien'; DROP TABLE x; --"])
    w = to_metricflow_where(f, MODEL)
    assert w == "{{ Dimension('region') }} = 'O''Brien''; DROP TABLE x; --'"


def test_semantic_validation():
    req = MetricRequest(metrics=["gross_margin"], group_by=["country"],
                        filters=[Filter(dimension="region", op="between", values=["A"])])
    errs = validate_request(req, MODEL)
    assert "unknown metric: gross_margin" in errs
    assert "unknown dimension: country" in errs
    assert any("between needs exactly 2" in e for e in errs)


def test_time_filter_compiles():
    f = Filter(dimension="metric_time__fiscal_quarter", op=">=", values=[dt.date(2026, 4, 1)])
    assert to_metricflow_where(f, MODEL) == "{{ TimeDimension('metric_time__fiscal_quarter') }} >= '2026-04-01'"


# ---- faithfulness ----
ROWS = [("Japan", Decimal("1234567.89"), -0.083), ("India", Decimal("2500000"), 0.041)]


def test_faithful_answer_passes():
    ok, bad = faithful("In FQ3 2026, Japan fell most: -8.3% to $1,234,567.89.", ROWS)
    assert ok, bad


def test_hallucinated_number_caught():
    ok, bad = faithful("Japan fell 12% to $1.5M.", ROWS)
    assert not ok and "12%" in bad


def test_derived_values_allowed():
    ok, _ = faithful("India exceeded Japan by 1,265,432.11.", ROWS, derived=[2500000 - 1234567.89])
    assert ok


# ---- comparator ----
def test_results_match_order_and_types():
    got_cols = ["net_revenue", "region"]
    got = [(1234567.890001, "Japan"), (2500000.0, "India")]
    exp_cols = ["region", "net_revenue"]
    exp = [("India", Decimal("2500000")), ("Japan", Decimal("1234567.89"))]
    ok, why = results_match(got_cols, got, exp_cols, exp)
    assert ok, why


def test_results_mismatch_detected():
    ok, _ = results_match(["region", "v"], [("Japan", 1.0)], ["region", "v"], [("Japan", 2.0)])
    assert not ok


# ---- scoped value index ----
def test_value_index_does_not_leak_across_scopes():
    apac, emea = scope_key({"region": ["APAC"]}), scope_key({"region": ["EMEA"]})
    idx = ScopedValueIndex([
        ValueEntry("certified.dim_customer", "name", "Acme Tokyo KK", apac),
        ValueEntry("certified.dim_customer", "name", "Acme GmbH", emea),
        ValueEntry("certified.fct_revenue", "region", "APAC", "public"),
    ])
    hits = idx.lookup("acme", apac, {"certified.dim_customer", "certified.fct_revenue"})
    assert [h.value for h in hits] == ["Acme Tokyo KK"]
    assert idx.lookup("acme", apac, {"certified.fct_revenue"}) == []


def test_scope_key_order_independent():
    assert scope_key({"a": ["2", "1"], "b": ["x"]}) == scope_key({"b": ["x"], "a": ["1", "2"]})


# ---- redaction ----
def test_redaction():
    out = redact_trace({"question": "orders for jane@x.com card 4111111111111111",
                        "result_rows": [[1], [2]], "nested": {"sql": "where acct = 123456789012"}})
    assert "[EMAIL]" in out["question"] and "[NUM]" in out["question"]
    assert out["result_rows"] == {"redacted": True, "count": 2}
    assert "[NUM]" in out["nested"]["sql"]


# ---- calibration ----
def test_threshold_meets_wrong_rate_target():
    scored = [(0.95, True)] * 60 + [(0.90, True)] * 30 + [(0.90, False)] * 2 + \
             [(0.80, True)] * 20 + [(0.80, False)] * 10
    thr, cov, wrong = choose_threshold(scored, max_wrong_rate=0.03)
    assert thr == 0.90 and wrong <= 0.03 and cov == pytest.approx(92 / 122)
