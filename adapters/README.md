# Adapters

This directory owns Qantara's downstream runtime boundary. The implemented interface and event rules are documented in [CONTRACT.md](CONTRACT.md) and [`protocols/agent.md`](../protocols/agent.md).

## Implementations

- `mock_adapter.py` — deterministic transport/UI test backend
- `runtime_skeleton.py` — adapter-path development skeleton
- `session_gateway_http.py` — generic Qantara session-contract HTTP backend
- `openai_compatible.py` — direct local `/v1/chat/completions` adapter
- `mcp_client.py` — MCP chat-tool adapter over stdio or streamable HTTP
- `factory.py` — adapter selection
- `base.py` — shared types, activity-event builder, and abstract interface

## Selection

| Setting | Result | Main companion settings |
|---|---|---|
| `QANTARA_ADAPTER=mock` | Mock adapter | none |
| `QANTARA_ADAPTER=runtime_skeleton` | Runtime skeleton | none |
| `QANTARA_ADAPTER=session_gateway_http` | Session HTTP adapter | `QANTARA_BACKEND_BASE_URL`, optional `QANTARA_BACKEND_TOKEN` |
| `QANTARA_ADAPTER=openai_compatible` | OpenAI-compatible adapter | `QANTARA_OPENAI_BASE_URL`, `QANTARA_OPENAI_MODEL`, optional API key |
| `QANTARA_ADAPTER=mcp` | MCP client adapter | `QANTARA_MCP_TRANSPORT` plus command or URL and chat tool |

Factory aliases are listed in [CONTRACT.md](CONTRACT.md). The source-checkout launcher maps `--backend` choices to these lower-level settings; see [`docs/CLI.md`](../docs/CLI.md).

## Adding an adapter

1. Implement every method in `RuntimeAdapter`.
2. Normalize output to agent-protocol events.
3. Register the implementation in `factory.py`.
4. Add contract, stream, cancellation, cleanup, and bound tests.
5. Document configuration, security boundary, status, and operator requirements.

Adapters keep the gateway runtime-agnostic. Backend reasoning, tools, and durable memory remain outside Qantara.
