#!/bin/sh
# DAST on the running reference stack (ADR 0012, #331): ZAP's API scan against /openapi.json,
# signed in as a reference-stack user, then the gate. Local use only; the stack must be up.
#   NEURON_IMAGE=neuron:ref make reference-up && sh scripts/dast_scan.sh [report-dir]
set -eu
out=${1:-dast-report}
mkdir -p "$out"
chmod 777 "$out"  # the ZAP container runs as another user
zap_image="ghcr.io/zaproxy/zaproxy@sha256:030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238"
# Keycloak access tokens last 5 minutes; a scan can take longer, so lengthen them for the run.
admin=$(curl -fsS --noproxy '*' -d grant_type=password -d client_id=admin-cli \
    -d username=admin -d password=admin-local-only \
    http://127.0.0.1:8180/realms/master/protocol/openid-connect/token |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -fsS --noproxy '*' -X PUT -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' \
    -d '{"realm":"neuron","accessTokenLifespan":3600}' \
    http://127.0.0.1:8180/admin/realms/neuron
token=$(sh scripts/reference_token.sh alice)
status=0
docker run --rm --network host -v "$(cd "$out" && pwd):/zap/wrk:rw" "$zap_image" zap-api-scan.py \
    -t http://127.0.0.1:8101/openapi.json -f openapi \
    -J zap-report.json -r zap-report.html -I \
    -z "-config replacer.full_list(0).description=auth \
-config replacer.full_list(0).enabled=true \
-config replacer.full_list(0).matchtype=REQ_HEADER \
-config replacer.full_list(0).matchstr=Authorization \
-config replacer.full_list(0).regex=false \
-config replacer.full_list(0).replacement=Bearer\ $token" || status=$?
echo "zap exit status: $status (0 clean, 1 fail, 2 warn, 3 error)"
[ "$status" -le 2 ] || exit 3
python3 scripts/dast_gate.py "$out/zap-report.json" deploy/reference/zap-rules.tsv
