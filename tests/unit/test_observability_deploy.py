"""Collector configuration and Prometheus alert rules (ADR 0007 decision 8, #96)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from neuron_agent.errors import base
from neuron_agent.observability import semconv
from neuron_agent.observability.metrics import LLM_LATENCY_BUCKETS

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY = _ROOT / "deploy" / "observability"
# Error budget of each SLO (OPERATIONS.md, set at the release gate #99).
_BUDGETS = {"availability": 0.005, "ttft": 0.10, "run_duration": 0.05, "provider_errors": 0.01}
_SLOS = set(_BUDGETS)
# Attributes only metrics carry, and the resource attributes that have their own list.
_METRIC_ONLY = {semconv.GEN_AI_USAGE_TYPE, semconv.NEURON_RULE}
_RESOURCE = {
    semconv.SERVICE_NAME,
    semconv.SERVICE_VERSION,
    semconv.DEPLOYMENT_ENVIRONMENT_NAME,
    semconv.SERVICE_INSTANCE_ID,
}


def _load(name: str) -> dict[str, Any]:
    loaded = yaml.safe_load((_DEPLOY / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _allowed(statements: list[dict[str, Any]], context: str) -> set[str]:
    """The keys of the `keep_keys` statement of one OTTL context."""
    (group,) = [g for g in statements if g["context"] == context]
    (statement,) = group["statements"]
    assert statement.startswith("keep_keys(attributes, [")
    keys: list[str] = yaml.safe_load(statement.removeprefix("keep_keys(attributes, ")[:-1])
    return set(keys)


def _attribute_constants() -> set[str]:
    skipped = ("METRIC_", "OPERATION_", "USAGE_TYPE_", "SEMCONV", "AGENT_NAME", "STREAM_SPAN")
    return {
        value
        for name, value in vars(semconv).items()
        if isinstance(value, str) and name.isupper() and not name.startswith(skipped)
    }


def test_collector_pipelines_order_and_exporters() -> None:
    config = _load("otel-collector.yaml")
    pipelines = config["service"]["pipelines"]
    assert set(pipelines) == {"traces", "metrics", "logs"}
    for pipeline in pipelines.values():
        processors = pipeline["processors"]
        assert processors[0] == "memory_limiter"
        assert processors[-1] == "batch"
        assert "transform/allowlist" in processors
        assert set(pipeline["exporters"]) <= set(config["exporters"])
        assert set(pipeline["processors"]) <= set(config["processors"])
    traces = pipelines["traces"]["processors"]
    assert (
        traces.index("transform/allowlist") < traces.index("tail_sampling") < traces.index("batch")
    )
    assert "prometheus" in pipelines["metrics"]["exporters"]
    assert any(name.startswith("otlp") for name in config["exporters"])
    assert config["exporters"]["otlp/backend"]["endpoint"].startswith("${env:")


def test_tail_sampling_keeps_errors_slow_traces_and_a_share_of_the_rest() -> None:
    policies = _load("otel-collector.yaml")["processors"]["tail_sampling"]["policies"]
    by_type = {policy["type"]: policy for policy in policies}
    assert by_type["status_code"]["status_code"]["status_codes"] == ["ERROR"]
    assert by_type["latency"]["latency"]["threshold_ms"] == 30000
    assert 0 < by_type["probabilistic"]["probabilistic"]["sampling_percentage"] < 100


def test_redaction_allow_lists_match_what_the_app_emits() -> None:
    config = _load("otel-collector.yaml")["processors"]["transform/allowlist"]
    assert config["error_mode"] == "propagate"
    attributes = _attribute_constants()

    for key in ("trace_statements", "metric_statements", "log_statements"):
        assert _allowed(config[key], "resource") == _RESOURCE

    spans = _allowed(config["trace_statements"], "span")
    assert spans >= attributes - _METRIC_ONLY - _RESOURCE
    assert semconv.HTTP_ROUTE in spans
    assert _allowed(config["trace_statements"], "spanevent") == set()

    assert _allowed(config["metric_statements"], "datapoint") == semconv.METRIC_ATTRIBUTE_ALLOW_LIST

    logs = _allowed(config["log_statements"], "log")
    assert logs <= attributes
    assert logs.isdisjoint({semconv.NEURON_RUN_ID, semconv.GEN_AI_CONVERSATION_ID})


def test_redaction_never_allows_content_or_identity_attributes() -> None:
    text = (_DEPLOY / "otel-collector.yaml").read_text(encoding="utf-8")
    for forbidden in (
        "gen_ai.input",
        "gen_ai.output",
        "system_instructions",
        "url.path",
        "user_agent",
    ):
        assert f'"{forbidden}' not in text


def _rules() -> list[dict[str, Any]]:
    return [rule for group in _load("prometheus-alerts.yaml")["groups"] for rule in group["rules"]]


def _alerts() -> list[dict[str, Any]]:
    return [rule for rule in _rules() if "alert" in rule]


def test_every_alert_error_class_has_burn_rate_alerts() -> None:
    codes = {
        cls.context.code
        for cls in vars(base).values()
        if isinstance(cls, type) and issubclass(cls, base.AppError) and cls.context.alert
    }
    assert codes
    for code in codes:
        mine = [a for a in _alerts() if a["labels"].get("error_type") == code]
        assert {a["labels"]["burn_rate"] for a in mine} == {"14.4", "6"}, code
        for alert in mine:
            assert f'error_type="{code}"' in alert["expr"]
    classes = {a["labels"]["error_type"] for a in _alerts() if "error_type" in a["labels"]}
    assert classes == codes  # no alert for a class that stopped alerting


@pytest.mark.parametrize("slo", sorted(_SLOS))
def test_every_slo_has_multi_window_burn_rate_alerts(slo: str) -> None:
    mine = [a for a in _alerts() if a["labels"].get("slo") == slo]
    # A 10% budget caps the burn rate at 10x, so ttft's fast page uses that instead of 14.4x.
    fast = "10" if slo == "ttft" else "14.4"
    assert {(a["labels"]["burn_rate"], a["labels"]["severity"]) for a in mine} == {
        (fast, "page"),
        ("6", "page"),
        ("1", "ticket"),
    }
    for alert in mine:
        assert " and " in alert["expr"]  # long and short window
        (threshold,) = {float(x) for x in re.findall(r">=? ([0-9.]+)", alert["expr"])}
        expected = float(alert["labels"]["burn_rate"]) * _BUDGETS[slo]
        assert threshold == pytest.approx(expected), alert["alert"]
        assert threshold <= 1  # a ratio above 1 can never fire
        assert alert["annotations"]["runbook_url"].endswith(f"#runbook-{slo.replace('_', '-')}")
    recorded = {r["record"] for r in _rules() if "record" in r}
    for alert in mine:
        used = {token for token in alert["expr"].split() if token.startswith("neuron:")}
        assert used and used <= recorded


def test_operations_documents_every_slo_and_alert_class() -> None:
    text = (_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "provisional until #99" not in text
    assert "**Targets were set at the v0.5.0 release gate (#99)**" in text
    assert "| `ttft` | streams whose time to first token is at most 15 s" in text
    for slo in _SLOS:
        assert f"#### Runbook: {slo.replace('_', '-')}" in text
    for alert in _alerts():
        if "error_type" in alert["labels"]:
            assert f"`{alert['labels']['error_type']}`" in text


def test_slo_bounds_are_latency_bucket_bounds() -> None:
    texts = [
        (_DEPLOY / "prometheus-alerts.yaml").read_text(encoding="utf-8"),
        (_ROOT / "OPERATIONS.md").read_text(encoding="utf-8"),
    ]
    for text in texts:
        bounds = {float(b) for b in re.findall(r'le="([0-9.]+)"', text)}
        assert bounds == {15.0, 30.0}
        assert bounds <= set(LLM_LATENCY_BUCKETS)


# --- service-health and abuse alerts (#155) ---------------------------------------------------

_SIGNALS = {
    "no_metrics": "NeuronNoMetrics",
    "not_ready": "NeuronInstanceNotReady",
    "db_pool": "NeuronPostgresPoolSaturated",
    "thread_busy": "NeuronThreadBusyAnomaly",
    "too_many_concurrent_runs": "NeuronTooManyConcurrentRunsAnomaly",
    "denied_tools": "NeuronDeniedToolCallsSpike",
}


def _signal_alerts() -> dict[str, dict[str, Any]]:
    return {a["labels"]["signal"]: a for a in _alerts() if "signal" in a["labels"]}


def _minutes(duration: str) -> int:
    match = re.fullmatch(r"(\d+)m", duration)
    assert match, duration
    return int(match.group(1))


def _prometheus_name(metric: str) -> str:
    return metric.replace(".", "_")


def test_every_metric_the_service_emits_is_documented_in_operations() -> None:
    text = (_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    names = {v for k, v in vars(semconv).items() if k.startswith("METRIC_") and isinstance(v, str)}
    assert {semconv.METRIC_SERVICE_READY, semconv.METRIC_DB_POOL_WAITING} <= names
    for name in sorted(names - {semconv.METRIC_HTTP_REQUEST_BODY_SIZE}):
        assert f"`{name}`" in text, name
    assert "`http.server.request.body.size`" in text


def test_new_gauges_carry_no_attribute_so_the_collector_allow_list_needs_no_entry() -> None:
    # The datapoint allow-list is exactly the label allow-list (checked above); a gauge with no
    # attributes at all passes through it, and tests/unit/test_metrics.py asserts it has none.
    keys = _allowed(
        _load("otel-collector.yaml")["processors"]["transform/allowlist"]["metric_statements"],
        "datapoint",
    )
    assert keys == semconv.METRIC_ATTRIBUTE_ALLOW_LIST


def test_service_health_and_rejection_alerts_exist_with_the_documented_severity() -> None:
    found = _signal_alerts()
    assert {signal: alert["alert"] for signal, alert in found.items()} == _SIGNALS
    severities = {signal: alert["labels"]["severity"] for signal, alert in found.items()}
    assert severities == {
        "no_metrics": "page",
        "not_ready": "page",
        "db_pool": "page",
        "thread_busy": "ticket",
        "too_many_concurrent_runs": "ticket",
        "denied_tools": "ticket",
    }
    for alert in found.values():
        assert alert["annotations"]["summary"]
        assert "slo" not in alert["labels"] and "error_type" not in alert["labels"]


def test_no_metrics_alert_fires_ten_minutes_after_the_last_push() -> None:
    alert = _signal_alerts()["no_metrics"]
    assert alert["expr"] == f"absent({_prometheus_name(semconv.METRIC_SERVICE_READY)})"
    exporter = _load("otel-collector.yaml")["exporters"]["prometheus"]
    # The series disappears when the Collector expires it, and the alert waits `for` after that.
    assert _minutes(exporter["metric_expiration"]) + _minutes(alert["for"]) == 10


def test_not_ready_and_pool_alerts_read_the_new_gauges_for_five_minutes() -> None:
    found = _signal_alerts()
    ready = _prometheus_name(semconv.METRIC_SERVICE_READY)
    pool = _prometheus_name(semconv.METRIC_DB_POOL_WAITING)
    assert found["not_ready"]["expr"] == f"{ready} == 0"
    assert found["db_pool"]["expr"] == f"{pool} > 0"
    assert found["not_ready"]["for"] == found["db_pool"]["for"] == "5m"


def test_rejection_alerts_use_the_error_class_metric_and_real_error_codes() -> None:
    found = _signal_alerts()
    assert base.ThreadBusyError.context.code == "thread_busy"
    assert base.ConcurrentRunsExceededError.context.code == "too_many_concurrent_runs"
    for signal in ("thread_busy", "too_many_concurrent_runs"):
        expr = found[signal]["expr"]
        assert f'neuron_agent_errors_total{{error_type="{signal}"}}' in expr
        assert 'http_route=~"/v1/.*"' in expr and "> 0.05" in expr
        assert found[signal]["for"] == "15m"


def test_denied_tool_alert_selects_exactly_the_rules_the_tool_guard_records() -> None:
    expr = _signal_alerts()["denied_tools"]["expr"]
    (selector,) = re.findall(r'neuron_agent_policy_blocks_total\{neuron_rule=~"([^"]+)"\}', expr)
    rules = set(selector.split("|"))
    assert rules == {"insufficient_scope", "unknown_tool"}
    guard = (_ROOT / "src" / "neuron_agent" / "models" / "factory.py").read_text("utf-8")
    for rule in rules:
        assert f'metrics.record_policy_block("{rule}")' in guard


def test_every_alert_runbook_link_resolves_to_a_heading_in_operations() -> None:
    text = (_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    anchors = {
        "runbook-" + heading.lower().replace(" ", "-")
        for heading in re.findall(r"^#### Runbook: (.+)$", text, flags=re.MULTILINE)
    }
    for alert in _alerts():
        file, _, anchor = alert["annotations"]["runbook_url"].partition("#")
        assert file == "OPERATIONS.md" and anchor in anchors, alert["alert"]


def test_operations_and_security_describe_the_new_alerts() -> None:
    operations = (_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    security = (_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for name in _SIGNALS.values():
        assert f"`{name}`" in operations, name
    assert "no example alert covers" not in security
    assert "`NeuronDeniedToolCallsSpike`" in security
