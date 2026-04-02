# Handoff

Current version: `0.1.0-alpha.2`

## Objective

Qantara is a LAN-first voice gateway for OpenClaw-compatible agent runtimes. It owns voice transport, STT/TTS, playback control, endpointing, and adapter boundaries. It does not own downstream tool execution or long-term conversation state.

## Current Validated State

- secure spike works on LAN over `HTTPS/WSS`
- browser microphone capture is working
- browser playback is working
- `faster-whisper` is validated for STT
- `Piper` is validated for TTS
- first spoken chunk is now commonly around `1.4s` to `1.6s`, with occasional higher outliers
- local playback clear is effectively immediate
- session-oriented HTTP adapter path is working
- local fake backend is working
- real Ollama session backend is working
- end-to-end cancel is working
- endpoint-ready auto-submit flow is working
- hands-free auto-submit is now gated against active turns, active playback, and short post-playback re-entry
- the local baseline is currently better than the recent LAN Ollama experiments
- browser-side disconnects observed in recent runs are clean closes (`code=1000`), not transport crashes
- the local backend now has deterministic fast paths for recurring voice cases:
  - greeting
  - identity / `Qantara` alias questions
  - capability prompts
  - casual chat prompts
  - short story requests
  - translation requests
- backend history is now bounded to a sliding window for the local `7b` model

## Runtime Shape

Current runtime chain:

- browser client
- Qantara gateway spike
- `session_gateway_http` adapter
- local Ollama session backend

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
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 \
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

- first TTS chunk: commonly about `1.4s` to `1.6s`
- occasional first-chunk outliers still occur above `2.0s`
- local clear acknowledgement: near-immediate
- local stop after clear: tens of milliseconds
- current preferred real backend baseline:
  - local Ollama on `127.0.0.1:11434`
  - model: `qwen2.5:7b`

## Known Weaknesses

- `Piper` is still slow enough to be noticeable
- VAD is improved but not yet fully tuned
- weak or junk speech filtering is improved but still heuristic
- some STT variants still need targeted handling if they recur in real runs
- response quality is more stable now, but only for the currently covered voice cases
- real backend integration is no longer deferred; it is active but still early

## Recommended Next Steps

1. Keep validating the improved local baseline in repeated real voice runs.
2. Extend deterministic handling only for recurring real-world STT variants, not speculatively.
3. Decide whether to keep optimizing `Piper` or evaluate a faster TTS path.
4. Revisit browser-side VAD thresholds only if real speech is still being skipped too often.

Latest tuning change:

- browser-side submit gating now blocks auto-submit during:
  - active backend turns
  - active assistant playback
  - a short post-playback cooldown
- browser-side weak-speech filtering now skips some low-value speech fragments before STT submission
- backend-side deterministic reply handling now covers the most common short voice patterns seen in recent runs
- current decision:
  - use the local Ollama baseline for Alpha-stage validation
  - use Claude Code CLI for second-opinion and alternative-solution checks, not as the primary implementation path

## Notes For Another Coding Agent

- Keep the project runtime-agnostic.
- Do not bind to the user's current local OpenClaw agents unless explicitly requested.
- Preserve the `session-oriented backend` contract shape.
- Treat browser-perceived playback stop and backend stop telemetry as different things.
- Current preferred runtime for validation is local Ollama, not the LAN host experiments.
