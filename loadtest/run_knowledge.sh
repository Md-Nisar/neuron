#!/bin/sh
# The knowledge scenarios (RAG-09.06) on the running reference stack, with the worker and fake
# embeddings (KNOWLEDGE_ENABLED=true, `--profile knowledge`), then the baseline:
#   1. `knowledge`: upload and search users for LOAD_SECONDS; ingestion is recorded once the
#      uploads settle, from the server's timestamps.
#   2. `mix`: LOAD_CHAT_USERS chat users alone; 3. `chat_search`: the same beside the search users.
# Writes the step files to $1 (default loadtest-knowledge/) and $1/baseline.json. Runs the
# project's environment from `uv sync` (PYTHON overrides it), so nothing is built or installed.
set -eu
out=${1:-loadtest-knowledge}
py=${PYTHON:-.venv/bin/python}
mkdir -p "$out"
seconds=${LOAD_SECONDS:-180}
uploaders=${LOAD_UPLOAD_USERS:-8}
chat=${LOAD_CHAT_USERS:-30}
export LOAD_SEARCH_USERS=${LOAD_SEARCH_USERS:-8}
export LOAD_USERS=${LOAD_USERS:-$chat}
export LOAD_KNOWLEDGE_USERS=$((uploaders + LOAD_SEARCH_USERS))
export LOAD_THINK_SECONDS=${LOAD_THINK_SECONDS:-6}
export LOAD_STEP_SECONDS=$seconds LOAD_MAX_STEPS=1
"$py" -m loadtest.provision
run() {
    scenario=$1
    users=$2
    if [ "${LOAD_RESOURCES:-}" = 1 ]; then
        "$py" -m loadtest.resources sample --out "$out/$scenario.resources.jsonl" &
        sampler=$!
    fi
    LOAD_SCENARIO=$scenario LOAD_STEP_USERS=$users LOAD_RESULTS_FILE="$out/$scenario.jsonl" \
        LOAD_INGESTION_FILE="$out/$scenario.ingestion.json" \
        "$py" -m locust -f loadtest/locustfile.py --headless --only-summary \
        > "$out/$scenario.log" 2>&1 || true  # Locust exits 1 when any request failed
    if [ "${LOAD_RESOURCES:-}" = 1 ]; then
        kill -TERM "$sampler" 2>/dev/null || true
        wait "$sampler" 2>/dev/null || true
        "$py" -m loadtest.resources summarise --samples "$out/$scenario.resources.jsonl" \
            --steps "$out/$scenario.jsonl" > "$out/$scenario.resources.json"
    fi
}
run knowledge $((uploaders + LOAD_SEARCH_USERS))
run mix "$chat"
run chat_search $((chat + LOAD_SEARCH_USERS))
"$py" -m loadtest.knowledge baseline --steps "$out" \
    --image "${NEURON_IMAGE:-unknown}" --note "${LOAD_NOTE:-}" > "$out/baseline.json"
