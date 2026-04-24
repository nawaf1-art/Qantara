# Adapters

This directory owns Qantara's downstream runtime boundary.

Current adapter implementations:

- `mock_adapter.py`
  - synthetic adapter for transport and UI testing
- `runtime_skeleton.py`
  - adapter-path skeleton for development
- `session_gateway_http.py`
  - generic session-oriented HTTP backend contract
- `openai_compatible.py`
  - direct `/v1/chat/completions` adapter for Ollama, llama.cpp, vLLM, LM Studio, Jan, LiteLLM, and similar local servers
- `factory.py`
  - config-based adapter selection
- `base.py`
  - shared adapter types and abstract interface

Current selection rule:

- `QANTARA_ADAPTER=mock`
  - use the synthetic adapter
- `QANTARA_ADAPTER=runtime_skeleton`
  - use the real-adapter framework path without binding to a concrete runtime
- `QANTARA_ADAPTER=session_gateway_http`
  - use the generic session-oriented HTTP adapter
  - requires `QANTARA_BACKEND_BASE_URL`
- `QANTARA_ADAPTER=openai_compatible`
  - use the direct OpenAI-compatible adapter
  - requires `QANTARA_OPENAI_BASE_URL` and `QANTARA_OPENAI_MODEL`

This keeps the gateway runtime-agnostic while letting the codebase move beyond a hard-coded mock-only path.
