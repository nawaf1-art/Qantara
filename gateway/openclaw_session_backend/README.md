# OpenClaw Session Backend

Thin session-oriented backend that keeps Qantara's existing HTTP contract and
delegates turns to an OpenClaw agent through the supported CLI.

Current target:

- OpenClaw agent: `main` unless `QANTARA_OPENCLAW_AGENT_ID` is set

Environment:

```bash
export QANTARA_OPENCLAW_AGENT_ID=main
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
- passes Qantara voice turn context into OpenClaw, including language,
  translation mode, voice id, and speech-rate metadata
- runs each CLI turn in its own process group so barge-in cancellation can
  terminate the full subprocess tree cleanly
