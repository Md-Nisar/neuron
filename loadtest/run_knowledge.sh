#!/bin/sh
# The knowledge scenarios (RAG-09.06) on the running reference stack, with the worker and fake
# embeddings (KNOWLEDGE_ENABLED=true, `--profile knowledge`), then the baseline:
#   1. `knowledge`: upload and search users for LOAD_SECONDS; ingestion is recorded once the
#      uploads settle, from the server's timestamps.
#   2. `mix`: LOAD_CHAT_USERS chat users alone; 3. `chat_search`: the same beside the search users.
# Writes the step files to $1 (default loadtest-knowledge/) and $1/baseline.json.
set -eu
out=${1:-loadtest-knowledge}
mkdir -p "$out"
seconds=${LOAD_SECONDS:-180}
uploaders=${LOAD_UPLOAD_USERS:-8}
chat=${LOAD_CHAT_USERS:-30}
export LOAD_SEARCH_USERS=${LOAD_SEARCH_USERS:-8}
export LOAD_USERS=${LOAD_USERS:-$chat}
export LOAD_KNOWLEDGE_USERS=$((uploaders + LOAD_SEARCH_USERS))
export LOAD_THINK_SECONDS=${LOAD_THINK_SECONDS:-6}
export LOAD_STEP_SECONDS=$seconds LOAD_MAX_STEPS=1
uv run python -m loadtest.provision
run() {  # scenario, users
    if [ "${LOAD_RESOURCES:-}" = 1 ]; then
        uv run python -m loadtest.resources sample --out "$out/$1.resources.jsonl" &
        sampler=$!
    fi
    LOAD_SCENARIO=$1 LOAD_STEP_USERS=$2 LOAD_RESULTS_FILE="$out/$1.jsonl" \
        LOAD_INGESTION_FILE="$out/$1.ingestion.json" \
        uv run python -m locust -f loadtest/locustfile.py --headless --only-summary \
        > "$out/$1.log" 2>&1 || true  # Locust exits 1 when any request failed
    if [ "${LOAD_RESOURCES:-}" = 1 ]; then
        kill -TERM "$sampler" 2>/dev/null || true
        wait "$sampler" 2>/dev/null || true
        uv run python -m loadtest.resources summarise --samples "$out/$1.resources.jsonl" \
            --steps "$out/$1.jsonl" > "$out/$1.resources.json"
    fi
}
run knowledge $((uploaders + LOAD_SEARCH_USERS))
run mix "$chat"
run chat_search $((chat + LOAD_SEARCH_USERS))
uv run python -m loadtest.knowledge baseline --steps "$out" \
    --image "${NEURON_IMAGE:-unknown}" --note "${LOAD_NOTE:-}" > "$out/baseline.json"
