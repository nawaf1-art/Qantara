# Ollama Session Backend

This is the first real local backend target for Qantara.

It implements [`SESSION_GATEWAY_CONTRACT.md`](../../SESSION_GATEWAY_CONTRACT.md) and uses local Ollama streaming under the hood.

Purpose:

- replace the fake backend with a real text-generation backend
- keep Qantara runtime-agnostic
- avoid binding to the user's current local OpenClaw agents

## Default Runtime

- Ollama base URL: `http://127.0.0.1:11434`
- Default model: `qwen2.5:7b`
- Default backend port: `19120`

## Run

From the repo root:

```bash
QANTARA_REAL_BACKEND_HOST=127.0.0.1 \
QANTARA_REAL_BACKEND_PORT=19120 \
QANTARA_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
QANTARA_OLLAMA_MODEL=qwen2.5:7b \
./.venv/bin/python gateway/ollama_session_backend/server.py
```

## Pair With The Spike

```bash
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
./.venv/bin/python gateway/transport_spike/server.py
```

## Cancel Support

Cancel is currently `best_effort`.

The backend acknowledges cancel immediately and stops forwarding additional streamed text when the cancel flag is observed. It does not yet guarantee hard cancellation inside the underlying Ollama generation.
