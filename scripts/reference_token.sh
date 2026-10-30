#!/bin/sh
# Print an access token for a reference-stack user (default alice) from the local Keycloak.
# The realm's throwaway passwords are `dev-only-<username>`. Local use only.
set -eu
user=${1:-alice}
curl -fsS --noproxy '*' \
    -d grant_type=password -d client_id=neuron-dev-test \
    -d "username=$user" -d "password=dev-only-$user" \
    http://127.0.0.1:8180/realms/neuron/protocol/openid-connect/token |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
