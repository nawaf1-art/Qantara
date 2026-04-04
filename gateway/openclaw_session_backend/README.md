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

Current bridge behavior:

- uses a dedicated OpenClaw `--session-id` per Qantara session
- resumes that session when the browser reconnects with the same persistent
  client session id
- runs each CLI turn in its own process group so barge-in cancellation can
  terminate the full subprocess tree cleanly
