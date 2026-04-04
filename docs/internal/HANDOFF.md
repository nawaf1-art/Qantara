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
- real OpenClaw session backend bridge is working
- end-to-end cancel is working
- endpoint-ready auto-submit flow is working
- hands-free auto-submit is now gated against active turns, active playback, and short post-playback re-entry
- browser-side barge-in is working through `clear_playback`
- browser-side `Audio Mode` selection now distinguishes `Headset` vs `Speakers`
- `Speakers` mode now uses stricter playback-time barge-in and a longer post-playback cooldown
- browser-side disconnects observed in recent runs are clean closes (`code=1000`), not transport crashes
- Qantara now works end-to-end against the OpenClaw agent `spectra`
- browser spike now includes a minimal avatar layer with preset selection
- browser spike now includes voice-style presets and a speech speed control
- identity foundation docs and schemas now exist for avatar packs, avatar descriptors, voice registry, and lipsync
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
- OpenClaw session backend bridge

Current active real target:

- agent: `spectra`
- model: `openai-codex/gpt-5.4-mini`

## Important Files

- project summary: [`README.md`](../../README.md)
- current state: [`PROJECT_STATE.md`](PROJECT_STATE.md)
- roadmap: [`ROADMAP.md`](../../ROADMAP.md)
- backend contract: [`SESSION_GATEWAY_CONTRACT.md`](../../SESSION_GATEWAY_CONTRACT.md)
- browser spike: [`client/transport-spike/index.html`](../../client/transport-spike/index.html)
- gateway spike: [`gateway/transport_spike/server.py`](../../gateway/transport_spike/server.py)
- HTTP adapter: [`adapters/session_gateway_http.py`](../../adapters/session_gateway_http.py)
- fake backend: [`gateway/fake_session_backend/server.py`](../../gateway/fake_session_backend/server.py)
- OpenClaw bridge backend: [`gateway/openclaw_session_backend/server.py`](../../gateway/openclaw_session_backend/server.py)
- identity layer: [`identity/README.md`](../../identity/README.md)
- experiment notes: [`experiments/notes/transport-spike.md`](../../experiments/notes/transport-spike.md)

## How To Run

Install:

```bash
cd /path/to/Qantara
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
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
./.venv/bin/python gateway/transport_spike/server.py
```

Open:

```text
https://<lan-ip>:9443/spike
```

Run OpenClaw bridge backend:

```bash
QANTARA_REAL_BACKEND_PORT=19120 \
QANTARA_OPENCLAW_AGENT_ID=spectra \
./.venv/bin/python gateway/openclaw_session_backend/server.py
```

## Observed Baselines

- first TTS chunk: commonly about `1.4s` to `1.6s`
- occasional first-chunk outliers still occur above `2.0s`
- local clear acknowledgement: near-immediate
- local stop after clear: tens of milliseconds
- current active real backend for validation:
  - OpenClaw bridge on `127.0.0.1:19120`
  - target agent: `spectra`
  - agent model: `openai-codex/gpt-5.4-mini`
- previously validated model backends:
  - Host A Ollama on `192.168.68.69:11434` with `gemma4:26b`
  - local Ollama on `127.0.0.1:11434` with `qwen2.5:7b`

## Known Weaknesses

- `Piper` is still slow enough to be noticeable
- VAD is improved but not yet fully tuned
- weak or junk speech filtering is improved but still heuristic
- speaker-plus-mic runs still depend on heuristic protection rather than real echo cancellation
- some STT variants still need targeted handling if they recur in real runs
- response quality is more stable now, but only for the currently covered voice cases
- real backend integration is no longer deferred; it is active but still early
- OpenClaw bridge still uses the shared `agent:spectra:main` session under the current CLI path
- browser voice selection is still a playback-profile layer because only one real Piper model is installed
- the Phase 1 identity system is architected, but Avatar Studio and true backend multi-voice are not implemented yet

## Recommended Next Steps

1. Keep validating the current `spectra` OpenClaw path in repeated real voice runs.
2. Implement true backend `voice_id` support plus the first real `voices.json` registry.
3. Replace hardcoded avatar presets with descriptor-driven presets from the identity layer.
4. Revisit browser-side VAD thresholds only if real speech is still being skipped too often.

Latest tuning change:

- browser-side submit gating now blocks auto-submit during:
  - active backend turns
  - active assistant playback
  - a short post-playback cooldown
- browser-side weak-speech filtering now skips some low-value speech fragments before STT submission
- browser-side audio mode now persists and uses stricter speaker-mode behavior during and just after playback
- OpenClaw bridge now kills the full subprocess group on cancel and resets the shared OpenClaw session when switching HTTP sessions
- browser spike now includes avatar presets, voice presets, and speech speed control
- current decision:
  - keep the gateway focus primary and treat model quality as secondary
  - use the current active agent/backend only as a test target, not as a product decision
  - use Claude Code CLI selectively as reviewer and scoped co-developer, with Codex remaining the owner and integrator

## Notes For Another Coding Agent

- Keep the project runtime-agnostic.
- The repo is now explicitly allowed to use OpenClaw agents when requested; current target is `spectra`.
- Preserve the `session-oriented backend` contract shape.
- Treat browser-perceived playback stop and backend stop telemetry as different things.
- Current active real test target is the OpenClaw-backed `spectra` agent, but the gateway work should remain runtime-agnostic.
