# Adapters

This directory owns Qantara's downstream runtime boundary.

Current adapter implementations:

- `mock_adapter.py`
  - synthetic adapter for M0 and transport testing
- `runtime_skeleton.py`
  - first real-adapter framework path
  - does not bind to any concrete backend yet
- `session_gateway_http.py`
  - first concrete backend adapter target
  - expects a generic session-oriented HTTP backend contract
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

This keeps the gateway runtime-agnostic while letting the codebase move beyond a hard-coded mock-only path.
