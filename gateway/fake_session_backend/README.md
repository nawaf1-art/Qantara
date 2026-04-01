# Fake Session Backend

This is a tiny local backend that implements [`SESSION_GATEWAY_CONTRACT.md`](/home/nawaf/Projects/Qantara/SESSION_GATEWAY_CONTRACT.md).

Purpose:

- validate the `session_gateway_http` adapter end to end
- avoid binding Qantara to the user's current local OpenClaw agents
- provide a repeatable backend for session, turn, stream, and cancel behavior

## Run

From the repo root:

```bash
QANTARA_FAKE_BACKEND_HOST=127.0.0.1 QANTARA_FAKE_BACKEND_PORT=19110 ./.venv/bin/python gateway/fake_session_backend/server.py
```

## Pair With The Spike

In another terminal:

```bash
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19110 \
QANTARA_SPIKE_HOST=127.0.0.1 \
QANTARA_SPIKE_PORT=8765 \
./.venv/bin/python gateway/transport_spike/server.py
```

Or for LAN HTTPS:

```bash
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19110 \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
QANTARA_TLS_CERT=/home/nawaf/Projects/Qantara/ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=/home/nawaf/Projects/Qantara/ops/certs/qantara-key.pem \
./.venv/bin/python gateway/transport_spike/server.py
```
