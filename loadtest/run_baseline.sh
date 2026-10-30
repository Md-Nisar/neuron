#!/bin/sh
# Run every load scenario once on the running reference stack and write the step files to
# $1 (default loadtest-steps/). Parameters come from LOAD_* (see loadtest/locustfile.py).
set -eu
out=${1:-loadtest-steps}
mkdir -p "$out"
export LOAD_USERS=${LOAD_USERS:-300}
export LOAD_STEP_SECONDS=${LOAD_STEP_SECONDS:-90}
export LOAD_STEP_USERS=${LOAD_STEP_USERS:-30}
export LOAD_MAX_STEPS=${LOAD_MAX_STEPS:-10}
export LOAD_THINK_SECONDS=${LOAD_THINK_SECONDS:-6}
uv run python -m loadtest.provision
for scenario in ${LOAD_SCENARIOS:-new_thread follow_up approval mix}; do
    # LOAD_RESOURCES=1 also records CPU, memory and Postgres connections (loadtest/resources.py).
    if [ "${LOAD_RESOURCES:-}" = 1 ]; then
        uv run python -m loadtest.resources sample --out "$out/$scenario.resources.jsonl" &
        sampler=$!
    fi
    LOAD_SCENARIO=$scenario LOAD_RESULTS_FILE="$out/$scenario.jsonl" \
        uv run python -m locust -f loadtest/locustfile.py --headless --only-summary \
        > "$out/$scenario.log" 2>&1 || true  # Locust exits 1 when any request failed
    if [ "${LOAD_RESOURCES:-}" = 1 ]; then
        kill -TERM "$sampler" 2>/dev/null || true
        wait "$sampler" 2>/dev/null || true  # SIGTERM: a background job in sh ignores SIGINT
        uv run python -m loadtest.resources summarise --samples "$out/$scenario.resources.jsonl" \
            --steps "$out/$scenario.jsonl" > "$out/$scenario.resources.json"
    fi
done
