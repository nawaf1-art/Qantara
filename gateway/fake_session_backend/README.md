# Fake Session Backend

This deterministic local backend exercises the generic session HTTP adapter against the current [`adapters/CONTRACT.md`](../../adapters/CONTRACT.md) and [`protocols/agent.md`](../../protocols/agent.md) semantics.

It is intended for repeatable session, turn, stream, and cancellation checks without a model or agent runtime.

## Run

From the repository root:

```bash
QANTARA_FAKE_BACKEND_HOST=127.0.0.1 \
QANTARA_FAKE_BACKEND_PORT=19110 \
./.venv/bin/python gateway/fake_session_backend/server.py
```

Pair it with the gateway in another terminal:

```bash
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19110 \
./.venv/bin/python gateway/transport_spike/server.py
```

This manual pairing starts the lower-level gateway server directly so the explicit adapter variables remain authoritative.

For LAN HTTPS, add a strong auth token and follow [`ops/README.md`](../../ops/README.md) rather than publishing the native port directly.
