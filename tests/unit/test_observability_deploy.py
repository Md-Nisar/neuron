"""Collector configuration and Prometheus alert rules (ADR 0007 decision 8, #96)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from neuron_agent.errors import base
from neuron_agent.observability import semconv

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY = _ROOT / "deploy" / "observability"
_SLOS = {"availability", "ttft", "run_duration", "provider_errors"}
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
    assert {(a["labels"]["burn_rate"], a["labels"]["severity"]) for a in mine} == {
        ("14.4", "page"),
        ("6", "page"),
        ("1", "ticket"),
    }
    for alert in mine:
        assert " and " in alert["expr"]  # long and short window
        assert alert["annotations"]["runbook_url"].endswith(f"#runbook-{slo.replace('_', '-')}")
    recorded = {r["record"] for r in _rules() if "record" in r}
    for alert in mine:
        used = {token for token in alert["expr"].split() if token.startswith("neuron:")}
        assert used and used <= recorded


def test_operations_documents_every_slo_and_alert_class() -> None:
    text = (_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "provisional until #99" in text
    for slo in _SLOS:
        assert f"#### Runbook: {slo.replace('_', '-')}" in text
    for alert in _alerts():
        if "error_type" in alert["labels"]:
            assert f"`{alert['labels']['error_type']}`" in text
