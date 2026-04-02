# Handoff

Current version: `0.1.0-alpha.1`

## Objective

Qantara is a LAN-first voice gateway for OpenClaw-compatible agent runtimes. It owns voice transport, STT/TTS, playback control, endpointing, and adapter boundaries. It does not own downstream tool execution or long-term conversation state.

## Current Validated State

- secure spike works on LAN over `HTTPS/WSS`
- browser microphone capture is working
- browser playback is working
- `faster-whisper` is validated for STT
- `Piper` is validated for TTS
- first spoken chunk is now roughly `1.50s` to `1.52s`
- local playback clear is effectively immediate
- session-oriented HTTP adapter path is working
- local fake backend is working
- end-to-end cancel is working
- endpoint-ready auto-submit flow is working
- speaking works end to end, but hands-free auto-submit remains too eager during assistant playback

## Runtime Shape

Current runtime chain:

- browser client
- Qantara gateway spike
- `session_gateway_http` adapter
- local fake backend

This intentionally avoids binding to the user's local OpenClaw agents for now.

## Important Files

- project summary: [`README.md`](/home/nawaf/Projects/Qantara/README.md)
- current state: [`PROJECT_STATE.md`](/home/nawaf/Projects/Qantara/PROJECT_STATE.md)
- roadmap: [`ROADMAP.md`](/home/nawaf/Projects/Qantara/ROADMAP.md)
- backend contract: [`SESSION_GATEWAY_CONTRACT.md`](/home/nawaf/Projects/Qantara/SESSION_GATEWAY_CONTRACT.md)
- browser spike: [`client/transport-spike/index.html`](/home/nawaf/Projects/Qantara/client/transport-spike/index.html)
- gateway spike: [`gateway/transport_spike/server.py`](/home/nawaf/Projects/Qantara/gateway/transport_spike/server.py)
- HTTP adapter: [`adapters/session_gateway_http.py`](/home/nawaf/Projects/Qantara/adapters/session_gateway_http.py)
- fake backend: [`gateway/fake_session_backend/server.py`](/home/nawaf/Projects/Qantara/gateway/fake_session_backend/server.py)
- experiment notes: [`experiments/notes/transport-spike.md`](/home/nawaf/Projects/Qantara/experiments/notes/transport-spike.md)

## How To Run

Install:

```bash
cd /home/nawaf/Projects/Qantara
make spike-install
```

Run fake backend:

```bash
make fake-backend-run-venv
```

Run secure spike:

```bash
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19110 \
QANTARA_TLS_CERT=/home/nawaf/Projects/Qantara/ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=/home/nawaf/Projects/Qantara/ops/certs/qantara-key.pem \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
./.venv/bin/python gateway/transport_spike/server.py
```

Open:

```text
https://<lan-ip>:9443/spike
```

## Observed Baselines

- first TTS chunk: about `1.50s` to `1.52s`
- later TTS chunk: about `1.65s` to `1.67s`
- local clear acknowledgement: near-immediate
- local stop after clear: tens of milliseconds

## Known Weaknesses

- `Piper` is still slow enough to be noticeable
- VAD is improved but not yet fully tuned
- auto-submit currently over-segments speech during assistant playback
- socket disconnect behavior still needs characterization
- real backend integration is still deferred

## Recommended Next Steps

1. Replace the fake backend with the first real backend target when that choice is made.
2. Improve reconnect behavior after disconnects.
3. Revisit hands-free turn policy after real backend speaking is validated.
4. Decide whether to keep optimizing `Piper` or evaluate a faster TTS path.

Latest tuning change:

- browser-side VAD thresholds were tightened, endpoint silence was increased, and auto-submit cooldown was added after the first auto-submit milestone; this still needs validation in repeated runs
- current decision: do not block real backend work on this; treat it as a known interaction-quality limitation

## Notes For Another Coding Agent

- Keep the project runtime-agnostic.
- Do not bind to the user's current local OpenClaw agents unless explicitly requested.
- Preserve the `session-oriented backend` contract shape.
- Treat browser-perceived playback stop and backend stop telemetry as different things.
