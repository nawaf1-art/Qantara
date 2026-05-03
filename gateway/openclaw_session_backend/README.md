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
# Optional: set to deep only when you explicitly want /health to run an agent turn.
export QANTARA_OPENCLAW_HEALTH_MODE=shallow
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
- keeps `/health` shallow by default, so routine health checks do not create
  OpenClaw sessions or cold-start agents
- runs each CLI turn in its own process group so barge-in cancellation can
  terminate the full subprocess tree cleanly
