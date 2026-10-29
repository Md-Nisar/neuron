#!/bin/sh
# Two local API processes (same code as the image) against the compose Postgres and Keycloak,
# with the real NVIDIA model reached through the sandbox proxy. Needs LLM_* in the environment.
cd /home/user/neuron
export APP_ENV=development APP_AUTH_MODE=jwt APP_AUTH_ISSUER=http://localhost:8180/realms/neuron APP_AUTH_AUDIENCE=neuron-api
export APP_AUTH_JWKS_URL=http://127.0.0.1:8180/realms/neuron/protocol/openid-connect/certs APP_AUTH_ALGORITHMS='["RS256"]'
export APP_AUTH_ROLE_PERMISSIONS='{"neuron-user":["agent:approve","agent:invoke","feedback:write","memories:read","memories:write","threads:delete","threads:read","threads:write","tools:calculator","tools:forget","tools:recall","tools:remember"],"neuron-reader":["threads:read"]}'
export APP_IDENTITY_HASH_KEY=reference-stack-identity-key-local-only-0001 APP_CHECKPOINTER=postgres APP_MEMORY_ENABLED=true APP_LIMITS_BACKEND=postgres
export APP_POSTGRES_DSN='postgresql://neuron_app:app-local-only@127.0.0.1:5433/neuron?sslmode=disable'
export APP_ALLOWED_HOSTS='["localhost","127.0.0.1"]' APP_TRUSTED_PROXIES='[]' APP_RATE_LIMIT_ENABLED=true APP_USER_TOKEN_BUDGET=10000000
export NVIDIA_API_KEY="$LLM_API_KEY" APP_DEFAULT_MODEL="nvidia:$LLM_MODEL"
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt REQUESTS_CA_BUNDLE=/root/.ccr/ca-bundle.crt
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
APP_PORT=8101 .venv/bin/neuron-api > "$1/api-8101.log" 2>&1 &
APP_PORT=8102 .venv/bin/neuron-api > "$1/api-8102.log" 2>&1 &
