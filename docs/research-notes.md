# Research Notes

## Official Documentation Consulted

- LangChain agents: `create_agent` is the current configurable harness for model, tools, prompt, structured output, middleware, and state.
- LangChain structured output: schema types can be passed via `response_format`, and validated data is returned under `structured_response`.
- LangGraph Graph API: `StateGraph`, `START`, `END`, nodes, and explicit edges remain the core graph construction primitives.
- LangGraph persistence: checkpointers are short-term thread state; stores are long-term memory. Agent Server manages persistence when deployed there.
- LangGraph application structure: `langgraph.json` declares dependencies, graphs, and env file.
- LangGraph deployment: LangSmith Cloud/Agent Server is the managed production path; self-hosting is also possible.
- LangSmith evaluation: recommended workflow is dataset creation, evaluators, offline experiments, online monitoring, and feedback loops.

## Repository Patterns Inspected

- `langchain-ai/simple-agent-template`: adopted `uv`, `pyproject.toml`, `langgraph.json`, simple tools, and deployable graph entrypoint. Expanded structure for production boundaries and docs.
- `langchain-ai/langgraph-example-pyproject`: noted as archived; useful only as historical evidence for `pyproject.toml` deployment shape.
- `langchain-ai/open_deep_research`: confirms provider configurability and evaluation emphasis, but its multi-agent/research complexity is not justified here.
- `langchain-ai/react-agent`: useful ReAct template, but this project uses `create_agent` directly inside one graph node.

## Adopted Principles

- Keep graph control flow explicit.
- Keep tools small, deterministic, and testable.
- Separate transport, service, graph, agent, model, tools, settings, security, and observability.
- Avoid retrieval, subgraphs, multi-agent orchestration, and custom durable persistence until requirements demand them.
