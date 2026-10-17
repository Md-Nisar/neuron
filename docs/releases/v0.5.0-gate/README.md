# v0.5.0 telemetry gate (#99)

Reproducible check of two #99 exit criteria through a real OpenTelemetry Collector:

1. A streamed run with a tool call produces a linked trace, logs and metrics through the
   Collector, on the FastAPI path and on the Agent Server path.
2. No prompt, answer, tool argument, bearer token or raw `sub` appears in the telemetry.

| File | Role |
| --- | --- |
| `telemetry_gate.py` | Orchestrates everything and prints `[PASS]`/`[FAIL]` lines; writes `telemetry_gate.out` (`telemetry_gate.live.out` with `--live`). |
| `gate_model.py` | Scripted chat model: one `calculator` call, then an answer. Replaces only `factory.create_chat_model`; a no-op when `GATE_LIVE=1`. |
| `gate_server.py` | FastAPI launcher: the real app with the scripted model. |
| `gate_graph.py` | Agent Server graph: the shipped graph with the scripted model. The harness writes a `langgraph.json` (the repository's, with this graph) into its run directory. |
| `otel-collector.gate.yaml` | Overlay merged over `deploy/observability/otel-collector.yaml`. Its header lists every deviation from the shipped config. |
| `telemetry_gate.out` | Raw output of the recorded run. |

## Run

```bash
# otelcol-contrib from the release the shipped config pins (v0.120.0, linux amd64):
curl -sSLfO https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.120.0/otelcol-contrib_0.120.0_linux_amd64.tar.gz
# sha256 from that release's checksums file:
echo "81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb  otelcol-contrib_0.120.0_linux_amd64.tar.gz" | sha256sum -c
tar -xzf otelcol-contrib_0.120.0_linux_amd64.tar.gz otelcol-contrib
./otelcol-contrib --version  # this v0.120.0 release binary reports 0.120.1, as the recorded runs show

env -u OPENAI_API_KEY -u NVIDIA_API_KEY \
  uv run python docs/releases/v0.5.0-gate/telemetry_gate.py --otelcol ./otelcol-contrib
```

Runtime data goes to `--workdir` (default: `neuron-v050-telemetry-gate` in the system temp
directory). The harness creates it with mode 0700 and a `.telemetry-gate` marker, wipes it at
start (it refuses a non-empty directory without the marker) and removes it at the end, since
it holds prompts and answers, unless `--keep` is given. It holds:
`collector/{traces,metrics,logs}.jsonl` (the Collector's file exporters),
`logs/{fastapi,agent-server}.log` (server stdout), `collector.log` and `control/` (the
client-side stream transcripts, the leak scan's positive control). Ports: 4317/4318 (OTLP),
8889 (Prometheus exporter), 8888 (Collector self-metrics), 8791 (API), 2031 (Agent Server),
8792 (JWKS).

`--live` keeps the configured provider instead of the scripted model. Export the provider
settings first (for example `APP_DEFAULT_MODEL` and the provider's API key); `APP_*` variables
are passed through, then the gate's settings are applied over them. Variables whose names
contain `API_KEY`, `TOKEN`, `SECRET`, `PASSWORD` or `DSN` are removed from the servers'
environment, except that `--live` passes the provider key (`NVIDIA_API_KEY`,
`APP_NVIDIA_API_KEY`, `OPENAI_API_KEY` or `APP_OPENAI_API_KEY`) through and adds its value to
the leak scan. The Collector gets only `PATH`, `HOME` and the variables its configs expand.
Without `--live`, `APP_DEFAULT_MODEL=openai:gate-scripted-model` names the scripted model in
spans and metrics.

## What the harness does

- An in-process IdP double serves a JWKS; the servers run with `APP_AUTH_MODE=jwt` and
  one ES256 token per path, so a real `sub` exists to scan for.
- Both servers run with `APP_OTEL_ENABLED=true`, `APP_OTEL_TRACES_SAMPLE_RATIO=1.0` and
  OTLP/HTTP to the Collector. `OTEL_METRIC_EXPORT_INTERVAL=5000` (an SDK variable) makes
  metrics arrive in seconds instead of 60 s.
- FastAPI: one `POST /v1/agent/stream`. Agent Server (`langgraph dev`, with
  `LOG_JSON=true`): one `runs.stream` with `stream_subgraphs=True`.
- Spans, metrics and log records are read back from the Collector's file exporters, so the
  shipped allow-list, value redaction, tail sampling and batch processors are in the path.
- Leak scan: the prompt, its marker, the answer as received and its marker, the tool
  expression, its JSON arguments and the tool result, every bearer token, its payload and
  signature segments, the raw `sub` and, with `--live`, the provider key, over every Collector
  output file and every server log line.
