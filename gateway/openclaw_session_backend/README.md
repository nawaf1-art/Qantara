# OpenClaw Session Backend

Thin session-oriented backend that keeps Qantara's existing HTTP contract and
delegates turns to an OpenClaw agent through the supported CLI.

Current target:

- OpenClaw agent: `spectra`

Environment:

```bash
export QANTARA_OPENCLAW_AGENT_ID=spectra
export QANTARA_REAL_BACKEND_HOST=127.0.0.1
export QANTARA_REAL_BACKEND_PORT=19120
```

Run:

```bash
./.venv/bin/python gateway/openclaw_session_backend/server.py
```
