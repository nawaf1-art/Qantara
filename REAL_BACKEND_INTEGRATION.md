# Real Backend Integration

## Purpose

This document is the shortest path from the current fake backend setup to the first real backend target.

Qantara should keep the same adapter shape:

- `session_gateway_http`
- text-first turn submission
- streamed assistant output events
- optional cancel support

This step should not bind Qantara to the user's current local OpenClaw agents unless that choice is made explicitly later.

## Current Baseline

Already validated:

- browser client
- gateway transport spike
- `session_gateway_http` adapter
- local fake backend implementing the contract
- cancel acknowledgement path
- browser speaking path through `Piper`

So the remaining task is not inventing the contract. It is replacing the fake backend with a real backend that speaks the same contract.

## Minimum Requirements For The First Real Backend

The backend must provide:

- `GET /health`
- `POST /sessions`
- `POST /sessions/{session_handle}/turns`
- `GET /sessions/{session_handle}/turns/{turn_handle}/events`
- `POST /sessions/{session_handle}/turns/{turn_handle}/cancel`

Reference:

- [`SESSION_GATEWAY_CONTRACT.md`](/home/nawaf/Projects/Qantara/SESSION_GATEWAY_CONTRACT.md)

## Recommended First Steps

1. Stand up a real backend that implements the session gateway contract.
2. Point `QANTARA_BACKEND_BASE_URL` at that backend.
3. Leave the browser and voice gateway unchanged.
4. Verify:
   - session bootstrap
   - turn submission
   - streamed deltas
   - final response
   - cancel response

## First Concrete Real Backend

The repo now includes a first concrete real backend target:

- [`gateway/ollama_session_backend/server.py`](/home/nawaf/Projects/Qantara/gateway/ollama_session_backend/server.py)

This backend:

- implements the session gateway contract
- uses local Ollama streaming under the hood
- avoids binding Qantara to the user's current OpenClaw agents
- gives Qantara a real text-generation backend to validate against

## Environment Variables

Use the existing adapter mode:

```bash
export QANTARA_ADAPTER=session_gateway_http
export QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19110
```

Optional:

```bash
export QANTARA_BACKEND_TOKEN=...
export QANTARA_BACKEND_TIMEOUT=30
```

See:

- [`ops/session-backend.env.example`](/home/nawaf/Projects/Qantara/ops/session-backend.env.example)

## Validation Checklist

- health endpoint returns `ok`
- `POST /sessions` returns a stable `session_handle`
- `POST /turns` returns a `turn_handle`
- event stream sends deltas before final where possible
- cancel returns `acknowledged` or a clearly handled fallback
- backend-specific auth or routing details stay out of core gateway code

## Explicit Non-Goal

Do not patch Qantara directly against a one-off backend route shape. If a real backend does not match the contract, adapt the backend side or add a thin compatibility shim.
