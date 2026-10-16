"""v0.5.0 release gate (#99): telemetry through a real OpenTelemetry Collector.

Proves two exit criteria:

1. A streamed run with a tool call produces a linked trace, logs and metrics through the
   Collector, on the FastAPI path (`POST /v1/agent/stream`) and on the Agent Server path
   (`langgraph dev`, a streamed run of the shipped graph).
2. No prompt, answer, tool argument, bearer token or raw `sub` appears in any telemetry the
   Collector wrote or in any app/Agent Server log line.

The Collector runs `deploy/observability/otel-collector.yaml` merged with
`otel-collector.gate.yaml` (file exporters, a filelog receiver for the JSON app logs and a
fast, keep-all tail sampling; see that file). The servers are production code with only the
chat model replaced by `gate_model.GateToolModel` (one calculator call, then an answer).
`--live` keeps the configured provider: export its settings (for example
`APP_DEFAULT_MODEL` and the provider key) before running.

    uv run python docs/releases/v0.5.0-gate/telemetry_gate.py --otelcol /path/to/otelcol-contrib
"""

# ruff: noqa: S603, S607  (the harness starts the local processes it names, via uv)

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from langgraph_sdk import get_client

GATE_DIR = Path(__file__).resolve().parent
REPO = GATE_DIR.parents[2]
SHIPPED_COLLECTOR_CONFIG = REPO / "deploy/observability/otel-collector.yaml"
ISSUER, AUDIENCE = "https://idp.telemetry-gate.test/", "neuron-api"
JWKS_PORT, API_PORT, AGENT_SERVER_PORT = 8792, 8791, 2031
PROMETHEUS = "127.0.0.1:8889"
SCOPES = "agent:invoke threads:read tools:calculator"
FASTAPI_SERVICE, AGENT_SERVER_SERVICE = "neuron-gate-fastapi", "neuron-gate-agent-server"

RUN = uuid.uuid4().hex[:10]
FACTORS = (100_000 + secrets.randbelow(900_000), 100_000 + secrets.randbelow(900_000))
EXPRESSION = f"{FACTORS[0]} * {FACTORS[1]}"
PRODUCT = str(FACTORS[0] * FACTORS[1])
PROMPT_MARKER = f"gate-prompt-{RUN}"
ANSWER_MARKER = f"gate-answer-{RUN}"
SUB = f"gate-user-{RUN}"
PROMPT = (
    f"Use the calculator tool to compute {EXPRESSION}, then reply with the product and the "
    f"code word {ANSWER_MARKER}. Reference {PROMPT_MARKER}."
)

KEY = ec.generate_private_key(ec.SECP256R1())
JWK = {
    **json.loads(jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key())),
    "kid": "gate",
    "alg": "ES256",
    "use": "sig",
}

results: list[tuple[str, bool]] = []
lines_out: list[str] = []
# Every string that must never reach telemetry, by kind; answers are added as received.
forbidden: dict[str, str] = {}


def say(text: str) -> None:
    lines_out.append(text)
    print(text, flush=True)


def check(name: str, ok: bool, observed: object) -> None:
    results.append((name, ok))
    say(f"[{'PASS' if ok else 'FAIL'}] {name}: {observed}")


# --- identity provider double ----------------------------------------------------------


class Jwks(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"keys": [JWK]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def token() -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUB,
        "scope": SCOPES,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
    }
    value = jwt.encode(claims, KEY, algorithm="ES256", headers={"kid": "gate"})
    _, payload, signature = value.split(".")
    n = sum(kind.startswith("bearer token ") for kind in forbidden) + 1
    forbidden.update(
        {
            f"bearer token {n}": value,
            f"token {n} payload": payload,
            f"token {n} signature": signature,
        }
    )
    return value


# --- processes ------------------------------------------------------------------------


def server_env(live: bool, service: str) -> dict[str, str]:
    """The servers' environment: the gate's settings, no provider keys unless live."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("APP_", "LANGSMITH", "LANGCHAIN")) and (live or "API_KEY" not in k)
    }
    if live:
        env.update({k: v for k, v in os.environ.items() if k.startswith("APP_")})
    env.update(
        {
            "APP_ENV": "development",
            "APP_AUTH_MODE": "jwt",
            "APP_AUTH_ISSUER": ISSUER,
            "APP_AUTH_AUDIENCE": AUDIENCE,
            "APP_AUTH_JWKS_URL": f"http://127.0.0.1:{JWKS_PORT}/jwks.json",
            "APP_AUTH_ISSUER_ID": "gate",
            "APP_AUTH_AUDIT_SUCCESS_ENABLED": "true",
            "APP_IDENTITY_HASH_KEY": "t" * 40,
            "APP_CHECKPOINTER": "memory",
            "APP_RATE_LIMIT_ENABLED": "false",
            "APP_ENABLE_LANGSMITH": "false",
            "APP_OTEL_ENABLED": "true",
            "APP_OTEL_TRACES_SAMPLE_RATIO": "1.0",
            "APP_OTEL_SERVICE_NAME": service,
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
            # SDK setting, harness only: export metrics every 5 s instead of 60 s.
            "OTEL_METRIC_EXPORT_INTERVAL": "5000",
            "GATE_LIVE": "1" if live else "0",
            "GATE_TOOL_EXPRESSION": EXPRESSION,
            "GATE_ANSWER_MARKER": ANSWER_MARKER,
        }
    )
    if not live:
        # Name the scripted model in spans and metrics instead of the default provider model.
        env["APP_DEFAULT_MODEL"] = "openai:gate-scripted-model"
    return env


def wait_for(probe: Any, what: str, seconds: float) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = probe()
        except (httpx.TransportError, OSError, ValueError):
            value = None
        if value:
            return value
        time.sleep(0.5)
    raise RuntimeError(f"{what} did not happen within {seconds:.0f}s")


def stop(process: subprocess.Popen[bytes], name: str) -> None:
    """Graceful SIGTERM, so the SDK flushes spans and metrics on shutdown."""
    process.send_signal(signal.SIGTERM)
    try:
        code = process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait()
    say(f"  {name} stopped, exit code {code}")


def start_collector(otelcol: str, work: Path) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "GATE_OUT": str(work / "collector"),
        "GATE_APP_LOG_GLOB": str(work / "logs" / "*.log"),
        "OTEL_RECEIVER_HOST": "127.0.0.1",
        "PROMETHEUS_EXPORTER_ENDPOINT": PROMETHEUS,
        # `otlp/backend` is defined in the shipped config but in no gate pipeline.
        "OTEL_BACKEND_ENDPOINT": "127.0.0.1:1",
    }
    version = subprocess.run([otelcol, "--version"], capture_output=True, text=True, check=True)
    say(f"collector: {version.stdout.strip()}")
    configs = ["--config", str(SHIPPED_COLLECTOR_CONFIG)]
    subprocess.run([otelcol, "validate", *configs], env=env, check=True)
    say("collector: shipped config validated on its own")
    configs += ["--config", str(GATE_DIR / "otel-collector.gate.yaml")]
    subprocess.run([otelcol, "validate", *configs], env=env, check=True)
    say("collector: shipped config + gate overlay validated")
    process = subprocess.Popen(
        [otelcol, *configs],
        env=env,
        stdout=open(work / "collector.log", "wb"),  # noqa: SIM115
        stderr=subprocess.STDOUT,
    )
    wait_for(
        lambda: httpx.post("http://127.0.0.1:4318/v1/traces", json={}).status_code < 500,
        "collector start",
        30,
    )
    return process


# --- the two paths ----------------------------------------------------------------------


def fastapi_run(work: Path, live: bool) -> dict[str, Any]:
    say("FastAPI path: gate_server.py (real app, scripted model)" + (" [LIVE]" if live else ""))
    process = subprocess.Popen(
        ["uv", "run", "--project", str(REPO), "python", str(GATE_DIR / "gate_server.py")],
        cwd=work / "run",
        env={**server_env(live, FASTAPI_SERVICE), "GATE_PORT": str(API_PORT)},
        stdout=open(work / "logs" / "fastapi.log", "wb"),  # noqa: SIM115
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{API_PORT}"
    try:
        wait_for(lambda: httpx.get(f"{url}/health/live").status_code == 200, "API start", 90)
        bearer = token()
        events: list[tuple[str, dict[str, Any]]] = []
        transcript = [json.dumps({"message": PROMPT})]
        name = ""
        with httpx.stream(
            "POST",
            f"{url}/v1/agent/stream",
            headers={"Authorization": f"Bearer {bearer}", "X-Correlation-ID": f"gate-{RUN}"},
            json={"message": PROMPT},
            timeout=120,
        ) as response:
            status = response.status_code
            for line in response.iter_lines():
                transcript.append(line)
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    events.append((name, json.loads(line[6:])))
        (work / "control" / "fastapi-stream.txt").write_text("\n".join(transcript))
        counts = Counter(n for n, _ in events)
        started = next((d for n, d in events if n == "run_started"), {})
        final = next((d for n, d in events if n == "final"), {})
        tools = [d.get("name") for n, d in events if n == "tool_call"]
        answer = final.get("answer")
        check(
            "FastAPI: streamed run with a tool call completes",
            status == 200 and "calculator" in tools and counts["final"] == 1,
            f"HTTP {status}, events {dict(counts)}, tool_call={tools}",
        )
        if isinstance(answer, str) and answer:
            forbidden["FastAPI answer"] = answer
        time.sleep(7)  # one periodic metric export while the process is alive
    finally:
        stop(process, "API")
    return {
        "run_id": started.get("run_id"),
        "request_id": started.get("request_id"),
        "answer": answer,
    }


async def agent_server_stream(url: str, transcript: Path) -> dict[str, Any]:
    client = get_client(url=url, headers={"Authorization": f"Bearer {token()}"})
    thread = await client.threads.create()
    counts: Counter[str] = Counter()
    tool_chunks: list[str] = []
    values: dict[str, Any] = {}
    run_id = None
    async for part in client.runs.stream(
        thread["thread_id"],
        "main",
        input={"messages": [{"role": "user", "content": PROMPT}]},
        stream_mode=["values", "messages-tuple"],
        stream_subgraphs=True,
    ):
        counts[part.event] += 1
        with transcript.open("a") as out:
            out.write(json.dumps([part.event, part.data]) + "\n")
        if part.event == "metadata":
            run_id = part.data.get("run_id")
        elif part.event == "values":
            values = part.data
        elif part.event.startswith("messages") and isinstance(part.data, list) and part.data:
            message = part.data[0]
            for chunk in message.get("tool_call_chunks") or message.get("tool_calls") or []:
                if chunk.get("name"):
                    tool_chunks.append(chunk["name"])
    answer = (values.get("answer") or {}).get("answer")
    return {
        "thread_id": thread["thread_id"],
        "run_id": run_id,
        "counts": dict(counts),
        "tools": tool_chunks,
        "answer": answer,
    }


def agent_server_run(work: Path, live: bool) -> dict[str, Any]:
    say("Agent Server path: langgraph dev, gate_graph.py (shipped graph, scripted model)")
    log_path = work / "logs" / "agent-server.log"
    # The repository's langgraph.json, with the graph swapped for gate_graph.py. Written to
    # the run directory with absolute paths: `langgraph dev` resolves graph paths from cwd.
    config = json.loads((REPO / "langgraph.json").read_text())
    config["graphs"] = {"main": f"{GATE_DIR / 'gate_graph.py'}:graph"}
    config["dependencies"] = [str(REPO)]
    config.pop("env", None)  # settings come from the process environment only
    (work / "run" / "langgraph.json").write_text(json.dumps(config, indent=2))
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            str(REPO),
            "langgraph",
            "dev",
            "--config",
            str(work / "run" / "langgraph.json"),
            "--port",
            str(AGENT_SERVER_PORT),
            "--no-browser",
            "--no-reload",
        ],
        cwd=work / "run",
        # langgraph-api's JSON log format instead of its colored console format.
        env={**server_env(live, AGENT_SERVER_SERVICE), "LOG_JSON": "true", "LOG_COLOR": "false"},
        stdout=open(log_path, "wb"),  # noqa: SIM115
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{AGENT_SERVER_PORT}"
    try:
        wait_for(lambda: httpx.get(f"{url}/ok").status_code == 200, "langgraph dev start", 180)
        run = asyncio.run(agent_server_stream(url, work / "control" / "agent-server-stream.txt"))
        check(
            "Agent Server: streamed run with a tool call completes",
            "calculator" in run["tools"] and bool(run["answer"]),
            f"events {run['counts']}, tool calls streamed={run['tools']}, "
            f"answer present={bool(run['answer'])}",
        )
        if run["answer"]:
            forbidden["Agent Server answer"] = run["answer"]
        time.sleep(7)
    finally:
        stop(process, "langgraph dev")
    return run


# --- reading what came out of the Collector -------------------------------------------------


def _attrs(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    out = {}
    for item in items or []:
        value = item.get("value", {})
        out[item["key"]] = next(iter(value.values()), None) if value else None
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def collector_spans(work: Path) -> list[dict[str, Any]]:
    spans = []
    for batch in read_jsonl(work / "collector" / "traces.jsonl"):
        for rs in batch.get("resourceSpans", []):
            resource = _attrs(rs.get("resource", {}).get("attributes"))
            for ss in rs.get("scopeSpans", []):
                for span in ss.get("spans", []):
                    spans.append(
                        {
                            **span,
                            "service": resource.get("service.name"),
                            "attrs": _attrs(span.get("attributes")),
                        }
                    )
    return spans


def collector_metrics(work: Path) -> dict[str, dict[str, set[str]]]:
    """service -> metric name -> datapoint attribute keys seen."""
    out: dict[str, dict[str, set[str]]] = {}
    for batch in read_jsonl(work / "collector" / "metrics.jsonl"):
        for rm in batch.get("resourceMetrics", []):
            service = _attrs(rm.get("resource", {}).get("attributes")).get("service.name")
            for sm in rm.get("scopeMetrics", []):
                for metric in sm.get("metrics", []):
                    keys = out.setdefault(service, {}).setdefault(metric["name"], set())
                    for kind in ("histogram", "sum", "gauge", "exponentialHistogram"):
                        for point in metric.get(kind, {}).get("dataPoints", []):
                            keys.update(a["key"] for a in point.get("attributes", []))
    return out


def collector_logs(work: Path) -> list[dict[str, Any]]:
    records = []
    for batch in read_jsonl(work / "collector" / "logs.jsonl"):
        for rl in batch.get("resourceLogs", []):
            for sl in rl.get("scopeLogs", []):
                records.extend(sl.get("logRecords", []))
    return records


def app_log_lines(path: Path) -> list[dict[str, Any]]:
    """JSON log lines. Under Agent Server, langgraph-api's handler wraps each app record:
    the app's JSON line is the string `event` of langgraph-api's own JSON line, so the inner
    record is unwrapped (its non-null fields win over the wrapper's)."""
    lines = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
            event = record.get("event")
            if isinstance(event, str) and event.startswith("{"):
                inner = json.loads(event)
                record = {**record, **{k: v for k, v in inner.items() if v is not None}}
                record["wrapped"] = True
        except json.JSONDecodeError:
            continue
        lines.append(record)
    return lines


def span_tree(spans: list[dict[str, Any]], service: str) -> dict[str, Any] | None:
    """The trace of `service`'s `invoke_agent neuron` span, with its spans by id."""
    run = next(
        (s for s in spans if s["service"] == service and s["name"] == "invoke_agent neuron"),
        None,
    )
    if run is None:
        return None
    trace = [s for s in spans if s["traceId"] == run["traceId"]]
    return {"trace_id": run["traceId"], "run": run, "spans": {s["spanId"]: s for s in trace}}


def describe(tree: dict[str, Any]) -> str:
    spans = tree["spans"]
    parts = []
    for span in sorted(spans.values(), key=lambda s: int(s["startTimeUnixNano"])):
        parent = spans.get(span.get("parentSpanId", ""), {}).get("name", "<root>")
        if span.get("parentSpanId") and span["parentSpanId"] not in spans:
            parent = f"<missing {span['parentSpanId']}>"
        parts.append(f"{span['name']} <- {parent}")
    return "; ".join(parts)


def check_trace(tree: dict[str, Any] | None, label: str, expect_stream: bool) -> None:
    if tree is None:
        check(f"{label}: trace reached the Collector", False, "no invoke_agent span")
        return
    spans = tree["spans"]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for span in spans.values():
        by_name.setdefault(span["name"], []).append(span)
    run = tree["run"]
    chats = [s for n, group in by_name.items() if n.startswith("chat ") for s in group]
    tools = by_name.get("execute_tool calculator", [])
    links = {
        "chat <- invoke_agent": bool(chats)
        and all(s.get("parentSpanId") == run["spanId"] for s in chats),
        "execute_tool <- invoke_agent": bool(tools)
        and all(s.get("parentSpanId") == run["spanId"] for s in tools),
    }
    if expect_stream:
        stream = by_name.get("neuron.stream", [{}])[0]
        http = by_name.get("POST /v1/agent/stream", [{}])[0]
        links["invoke_agent <- neuron.stream"] = run.get("parentSpanId") == stream.get("spanId")
        links["neuron.stream <- POST /v1/agent/stream"] = bool(stream) and stream.get(
            "parentSpanId"
        ) == http.get("spanId")
        links["POST /v1/agent/stream is the root"] = bool(http) and not http.get("parentSpanId")
    check(
        f"{label}: one trace with correct parent links",
        all(links.values()) and len(chats) == 2 and len(tools) == 1,
        f"trace {tree['trace_id']}, {len(spans)} spans: {describe(tree)}; links {links}",
    )
    usage = [
        (s["attrs"].get("gen_ai.usage.input_tokens"), s["attrs"].get("gen_ai.usage.output_tokens"))
        for s in chats
    ]
    check(
        f"{label}: span attributes after the Collector",
        bool(run["attrs"].get("neuron.owner_key_prefix"))
        and all(t["attrs"].get("neuron.outcome") == "success" for t in tools)
        and all(u[0] is not None for u in usage),
        f"invoke_agent attrs {sorted(run['attrs'])}; chat usage {usage}; "
        f"tool outcome {[t['attrs'].get('neuron.outcome') for t in tools]}",
    )


def check_logs(
    tree: dict[str, Any] | None,
    label: str,
    lines: list[dict[str, Any]],
    records: list[dict[str, Any]],
    ids: dict[str, Any],
    required_events: set[str],
) -> None:
    if tree is None:
        check(f"{label}: logs linked to the trace", False, "no trace")
        return
    trace_id, span_ids = tree["trace_id"], set(tree["spans"])
    run_lines = [
        line
        for line in lines
        if line.get("trace_id") == trace_id
        or any(ids.get(k) and line.get(k) == ids[k] for k in ("run_id", "request_id"))
    ]
    unlinked = [
        line.get("event")
        for line in run_lines
        if line.get("trace_id") != trace_id or line.get("span_id") not in span_ids
    ]
    events = Counter(line.get("event") for line in run_lines)
    check(
        f"{label}: app log lines for the run carry its trace_id and a span_id of the trace",
        bool(run_lines) and not unlinked and required_events <= set(events),
        f"{len(run_lines)} lines {dict(events)}; unlinked {unlinked}; "
        f"{sum(bool(line.get('wrapped')) for line in run_lines)} wrapped in a langgraph-api line",
    )
    exported = [r for r in records if r.get("traceId") == trace_id]
    check(
        f"{label}: those log records came out of the Collector's logs pipeline linked",
        len(exported) >= len(run_lines) > 0 and all(r.get("spanId") in span_ids for r in exported),
        f"{len(exported)} records with traceId {trace_id}",
    )


def check_metrics(
    metrics: dict[str, dict[str, set[str]]], label: str, service: str, required: list[str]
) -> None:
    seen = metrics.get(service, {})
    missing = [name for name in required if name not in seen]
    check(
        f"{label}: metrics arrived through the Collector",
        not missing,
        f"present {sorted(n for n in required if n in seen)}; missing {missing}",
    )
    allowed = {
        "gen_ai.request.model",
        "gen_ai.provider.name",
        "gen_ai.operation.name",
        "gen_ai.tool.name",
        "gen_ai.token.type",
        "error.type",
        "http.route",
        "http.response.status_code",
        "neuron.outcome",
        "neuron.rule",
    }
    extra = {name: sorted(keys - allowed) for name, keys in seen.items() if keys - allowed}
    check(f"{label}: metric attributes are within the allow-list", not extra, extra or "none")


def find(work: Path, files: list[Path]) -> tuple[Counter[str], int]:
    hits: Counter[str] = Counter()
    lines = 0
    for path in files:
        for line in path.read_text(errors="replace").splitlines():
            lines += 1
            for kind, value in forbidden.items():
                if value and value in line:
                    hits[f"{kind} in {path.relative_to(work)}"] += 1
    return hits, lines


def scan(work: Path, live: bool) -> None:
    # Positive control: the client-side transcripts hold the content, so the scan must find it.
    control, _ = find(work, sorted((work / "control").iterdir()))
    found = {key.split(" in ")[0] for key in control}
    # A live model words its own answer, so only the scripted run's markers are certain.
    expected = {"prompt"} | {kind for kind in forbidden if kind.endswith(" answer")}
    if not live:
        expected |= {"answer marker", "tool result"}
    check(
        "leak scan positive control: content is found in the client-side stream transcripts",
        expected <= found,
        f"found {sorted(found)}",
    )
    files = sorted(p for p in work.rglob("*") if p.is_file() and p.suffix in {".jsonl", ".log"})
    hits, lines = find(work, files)
    check(
        f"leak scan: {len(forbidden)} forbidden strings in {lines} lines of {len(files)} files",
        not hits,
        dict(hits) or "no matches",
    )
    say(f"  forbidden kinds: {sorted(forbidden)}")
    say(f"  files: {[str(p.relative_to(work)) for p in files]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="use the configured provider")
    parser.add_argument("--otelcol", default=shutil.which("otelcol-contrib") or "otelcol-contrib")
    parser.add_argument(
        "--workdir", type=Path, default=Path(tempfile.gettempdir()) / "neuron-v050-telemetry-gate"
    )
    parser.add_argument("--out", type=Path, help="default: telemetry_gate[.live].out here")
    args = parser.parse_args()
    out = args.out or GATE_DIR / ("telemetry_gate.live.out" if args.live else "telemetry_gate.out")
    work: Path = args.workdir
    shutil.rmtree(work, ignore_errors=True)
    for sub in ("collector", "logs", "run", "control"):
        (work / sub).mkdir(parents=True)

    forbidden.update(
        {
            "prompt": PROMPT,
            "prompt marker": PROMPT_MARKER,
            "answer marker": ANSWER_MARKER,
            "tool expression": EXPRESSION,
            "tool arguments (JSON)": json.dumps({"expression": EXPRESSION}),
            "tool result": PRODUCT,
            "raw sub": SUB,
        }
    )
    say(f"telemetry gate run {RUN} ({'LIVE provider' if args.live else 'scripted model'})")
    jwks = ThreadingHTTPServer(("127.0.0.1", JWKS_PORT), Jwks)
    threading.Thread(target=jwks.serve_forever, daemon=True).start()
    collector = start_collector(args.otelcol, work)
    prometheus = ""
    try:
        fastapi = fastapi_run(work, args.live)
        agent_server = agent_server_run(work, args.live)
        wait_for(
            lambda: (
                {s["service"] for s in collector_spans(work) if s["name"] == "invoke_agent neuron"}
                >= {FASTAPI_SERVICE, AGENT_SERVER_SERVICE}
            ),
            "both traces at the Collector output (tail sampling decision_wait 10 s)",
            90,
        )
        time.sleep(3)
        prometheus = httpx.get(f"http://{PROMETHEUS}/metrics").text
    finally:
        stop(collector, "collector")

    spans, metrics, records = collector_spans(work), collector_metrics(work), collector_logs(work)
    say(
        f"collector output: {len(spans)} spans, {sum(len(m) for m in metrics.values())} "
        f"metric streams, {len(records)} log records"
    )

    say("-- criterion 1: FastAPI path --")
    tree = span_tree(spans, FASTAPI_SERVICE)
    check_trace(tree, "FastAPI", expect_stream=True)
    check_logs(
        tree,
        "FastAPI",
        app_log_lines(work / "logs" / "fastapi.log"),
        records,
        fastapi,
        {"stream_started", "tool_call_succeeded", "model_token_usage", "stream_completed"},
    )
    check_metrics(
        metrics,
        "FastAPI",
        FASTAPI_SERVICE,
        [
            "gen_ai.client.operation.duration",
            "gen_ai.client.token.usage",
            "neuron.agent.run.duration",
            "neuron.agent.stream.ttft",
            "neuron.agent.tool.duration",
            "http.server.request.duration",
        ],
    )
    prom_names = [
        "gen_ai_client_operation_duration_seconds_count",
        "gen_ai_client_token_usage_count",
        "neuron_agent_run_duration_seconds_count",
        "neuron_agent_stream_ttft_seconds_count",
        "neuron_agent_tool_duration_seconds_count",
        "http_server_request_duration_seconds_count",
    ]
    missing = [n for n in prom_names if n not in prometheus]
    check(
        "Prometheus exporter serves the names the alert rules use",
        not missing,
        f"missing {missing}" if missing else f"all {len(prom_names)} present",
    )

    say("-- criterion 1: Agent Server path --")
    tree = span_tree(spans, AGENT_SERVER_SERVICE)
    check_trace(tree, "Agent Server", expect_stream=False)
    check_logs(
        tree,
        "Agent Server",
        [
            line
            for line in app_log_lines(work / "logs" / "agent-server.log")
            if str(line.get("logger", "")).startswith("neuron_agent")
        ],
        records,
        {"run_id": agent_server["run_id"]},
        {"tool_call_succeeded", "model_token_usage"},
    )
    check_metrics(
        metrics,
        "Agent Server",
        AGENT_SERVER_SERVICE,
        [
            "gen_ai.client.operation.duration",
            "gen_ai.client.token.usage",
            "neuron.agent.run.duration",
            "neuron.agent.tool.duration",
        ],
    )

    say("-- criterion 2: no content, tokens or raw sub in telemetry --")
    scan(work, args.live)
    passed = sum(ok for _, ok in results)
    say(f"{passed}/{len(results)} checks passed")
    out.write_text("\n".join(lines_out) + "\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
