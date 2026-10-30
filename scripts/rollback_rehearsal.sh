#!/bin/sh
# Rollback rehearsal on the reference stack (ADR 0012, #333): OPERATIONS.md, "Rollback".
#   sh scripts/rollback_rehearsal.sh OLD_IMAGE NEW_IMAGE
# Deploys NEW_IMAGE (its `setup` migrates), creates a thread, redeploys OLD_IMAGE over the
# migrated database (its `setup` runs too), checks readiness, the smoke test and that the
# thread is still readable and that the old image can still write a rating (a row in
# `neuron_feedback`, which a newer release may have extended), then rolls forward again.
# Prints one line per step.
set -eu
old=${1:?old image}
new=${2:?new image}
compose="docker compose -f docker-compose.reference.yml"
step() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
token() { sh scripts/reference_token.sh "${1:-alice}"; }
smoke() {
    for port in 8101 8102; do
        SMOKE_TEST_TOKEN=$(token) uv run python scripts/smoke_test.py "http://127.0.0.1:$port" 2>&1 |
            grep -v UV_NATIVE
    done
}
migrations() { docker exec "$(NEURON_IMAGE=$new $compose ps -q postgres)" psql -U neuron_owner -d neuron -tAc \
    "SELECT string_agg(version::text, ',' ORDER BY version) FROM neuron_migrations"; }

NEURON_IMAGE=$new $compose down -v >/dev/null 2>&1 || true
step "deploy new image $new"
NEURON_IMAGE=$new $compose up -d --wait >/dev/null
step "migrations after new: $(migrations)"
smoke
stream=$(curl -fsS --noproxy '*' -N -m 30 -H "Authorization: Bearer $(token)" \
    -H 'Content-Type: application/json' -d '{"message":"before rollback"}' \
    http://127.0.0.1:8101/v1/agent/stream)
thread=$(printf '%s\n' "$stream" | sed -n 's/^data: .*"thread_id": "\([0-9a-f-]*\)".*/\1/p' | head -1)
run=$(printf '%s\n' "$stream" | sed -n 's/^data: .*"run_id": "\([0-9a-f-]*\)".*/\1/p' | head -1)
step "created thread $thread run $run"
columns() { docker exec "$(NEURON_IMAGE=$new $compose ps -q postgres)" psql -U neuron_owner -d neuron -tAc \
    "SELECT string_agg(column_name, ',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name = 'neuron_feedback'"; }
step "neuron_feedback columns under the new image: $(columns)"
step "roll back to $old (setup runs first, then both replicas)"
NEURON_IMAGE=$old $compose up -d --wait >/dev/null
step "migrations after rollback: $(migrations)"
for port in 8101 8102; do
    curl -fsS --noproxy '*' "http://127.0.0.1:$port/health/ready" >/dev/null && step "ready on $port"
done
smoke
rated=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' -X POST -H "Authorization: Bearer $(token)" \
    -H 'Content-Type: application/json' -d '{"score": 1, "reason": "helpful"}' \
    "http://127.0.0.1:8101/v1/threads/$thread/runs/$run/feedback")
step "old image wrote a rating over the migrated table: HTTP $rated"
code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' -H "Authorization: Bearer $(token)" \
    "http://127.0.0.1:8102/v1/threads/$thread/messages")
step "thread readable on the old image via the other replica: HTTP $code"
step "roll forward again to $new"
NEURON_IMAGE=$new $compose up -d --wait >/dev/null
smoke
[ "$code" = 200 ] && [ "$rated" = 200 ] && step "rollback rehearsal passed" || { step "rollback rehearsal FAILED"; exit 1; }
