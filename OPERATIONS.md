# Operations

## Deployment

Two deployment paths are supported:

- LangGraph Agent Server/LangSmith using `langgraph.json`.
- Self-hosted container using `Dockerfile`.

Production deployments must inject secrets through the platform secret manager.

## Health Checks

- `/health/live`: process is serving requests.
- `/health/ready`: application configuration loaded.

Health checks intentionally avoid LLM calls to prevent cost spikes and dependency coupling.

## Logs and Traces

Logs are JSON and include service metadata. Enable LangSmith tracing by setting:

```text
APP_ENABLE_LANGSMITH=true
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=neuron-agent-production
```

Do not log raw secrets, authorization headers, or sensitive user content.

## Scaling

The API can scale horizontally. Durable conversations require Agent Server managed persistence or an explicit production checkpointer/store.

## Rollback

Rollback by redeploying the previous container image or reverting the LangSmith deployment to the previous repository revision. Before removing graph nodes or state fields, verify no active threads depend on them.

## Common Failures

- Missing provider key: live model calls fail; staging/production settings validate this early.
- Missing development provider key: the app starts with a fake local chat model for non-production checks.
- Provider timeout: classified as model execution failure.
- Invalid tool input: returned as validation error.
- LangSmith unavailable: core request handling should continue unless tracing is made mandatory by deployment policy.
