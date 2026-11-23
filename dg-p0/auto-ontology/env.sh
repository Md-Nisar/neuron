# DG-00.04: environment for Auto Ontology at 7dac5ff7, run natively (see README.md).
# Source it:  AO_LOCAL_ENV=/path/to/local.env . env.sh
# Needs LLM_API_KEY and LLM_MODEL in the environment. Nothing here holds a secret: the key comes
# from LLM_API_KEY, and the throwaway local passwords (POSTGRES_PASSWORD,
# AUTO_ONTOLOGY_ADMIN_PASSWORD, AUTH_SECRET) from AO_LOCAL_ENV, a file outside the repository.
: "${LLM_API_KEY:?}" "${LLM_MODEL:?}" "${AO_LOCAL_ENV:?}"
set -a
. "$AO_LOCAL_ENV"
# Auto Ontology's own metadata store (pgvector/pgvector:pg17 in Docker, port 55433).
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=55433
POSTGRES_USER=postgres
POSTGRES_DATABASE=auto_ontology
# The mart: D3 through its own read-only login (ao_reader.sql), over the spike cluster's socket.
# DG-00.05 (AO_DATASETS=all): also D1 and the 11 D2 databases, through their own read-only logins
# (ao_reader_d1_d2.sql, ../d2/load.sh).
_sock="host=/var/lib/postgresql/dg-spike&port=55432"
CONNECTION_STRINGS="postgresql://d3_ao_reader@/d3?$_sock"
if [ "${AO_DATASETS:-d3}" = all ]; then
  CONNECTION_STRINGS="$CONNECTION_STRINGS,postgresql://d1_ao_reader@/d1?$_sock"
  for _db in california_schools card_games codebase_community debit_card_specializing european_football_2 \
             financial formula_1 student_club superhero thrombosis_prediction toxicology; do
    CONNECTION_STRINGS="$CONNECTION_STRINGS,postgresql://d2_ao_reader@/d2_$_db?$_sock"
  done
fi
# Chat: the same model as arms B and C. Embeddings and rerank: upstream's NVIDIA defaults.
DEFAULT_MODELS_ENDPOINT=https://integrate.api.nvidia.com/v1
DEFAULT_MODELS_API_KEY="$LLM_API_KEY"
DEFAULT_MODELS_MODEL="$LLM_MODEL"
REASONING_MODEL="$LLM_MODEL"
NON_REASONING_MODEL="$LLM_MODEL"
EMBED_ENDPOINT=https://integrate.api.nvidia.com/v1
EMBED_MODEL=nvidia/nemotron-3.5-embed-1b
RERANK_ENDPOINT=https://ai.api.nvidia.com/v1/retrieval/nvidia/nemotron-3.5-rerank-8b/reranking
RERANK_MODEL=nvidia/nemotron-3.5-rerank-8b
# Services on loopback only. The backend trusts an unauthenticated user header, so only the
# frontend may reach it.
APP_URL=http://127.0.0.1:3000
PYTHON_API_URL=http://127.0.0.1:3001
INGESTION_SERVICE_URL=http://127.0.0.1:3002
AUTO_ONTOLOGY_MCP_PUBLIC_URL=http://127.0.0.1:3003
AUTO_ONTOLOGY_ADMIN_EMAIL=admin@example.test
# Every outbound HTTPS connection goes through the logging proxy (egress_log.py).
HTTPS_PROXY=http://127.0.0.1:38999
https_proxy=http://127.0.0.1:38999
NO_PROXY=localhost,127.0.0.1
no_proxy=localhost,127.0.0.1
set +a
