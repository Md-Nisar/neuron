# ADR 0001: Main Agent Architecture

## Status

Accepted.

## Problem

This repository needed a production-grade LangChain/LangGraph agent baseline without a domain-specific requirement for retrieval, multiple agents, durable custom persistence, or high-impact side effects.

## Requirements

- Runnable Python package with LangGraph deployment metadata.
- Explicit API, service, graph, agent, tool, config, security, and observability boundaries.
- Deterministic tests that do not require live LLM credentials.
- Optional live provider execution through configuration.
- Documentation suitable for future maintainers.

## Options Considered

1. Simple LangChain agent: smallest runtime, but weak separation around API/service/graph state.
2. LangChain agent plus middleware: useful later for richer cross-cutting behavior, but not required for current functionality.
3. Custom LangGraph workflow: selected; keeps control flow explicit while still using `create_agent` for the model/tool loop.
4. Multi-agent/subgraph architecture: rejected until independent workflows or team-owned subgraphs exist.
5. Background/async execution architecture: rejected until long-running or queued workloads are required.

## Decision

Use one LangGraph `StateGraph` with a single `agent` node. The node invokes a LangChain `create_agent` harness configured with a prompt, two read-only tools, and an `AgentAnswer` structured output schema. HTTP transport is kept in FastAPI, orchestration in the graph, and request normalization in an application service.

## Consequences

The architecture is intentionally narrow. It is easy to test and deploy through LangGraph Agent Server, but it does not yet include long-term memory, retrieval, background queues, human approval, or production database persistence. Those can be added behind existing boundaries when product requirements justify them.
