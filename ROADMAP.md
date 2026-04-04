# Roadmap

Current version: `0.1.3`

This roadmap is the single source of truth for what to build and in what order. It is designed to be read by humans, Claude Code, and Codex alike.

Each task has a clear scope, acceptance criteria, and the files involved. Tasks within a phase can be worked on in parallel unless marked as dependent.

Each phase includes **early releases** — small, shippable wins that go out as GitHub releases before the full phase is complete. This keeps the project visibly alive and gives users something new every 1-2 weeks.

---

## Phase 0: Alpha Checkpoint — COMPLETE

Version: `0.1.0-alpha.2`

- [x] Browser mic capture to gateway over WebSocket PCM
- [x] Gateway-side VAD and endpointing
- [x] faster-whisper STT integration
- [x] Piper TTS integration with chunked playback (~1.5s first audio)
- [x] Adapter framework with mock, skeleton, and HTTP adapters
- [x] Session-oriented HTTP backend contract
- [x] Fake backend for testing
- [x] Ollama backend with real model conversation
- [x] OpenClaw backend bridge
- [x] Barge-in with immediate playback cancel
- [x] Auto-submit on endpoint-ready
- [x] HTTPS/WSS for LAN access
- [x] Avatar system with lipsync contract
- [x] Apache 2.0 license

---

## Phase 1: "It Just Works" — IN PROGRESS

**Goal:** Anyone can go from zero to a working local voice agent in under 60 seconds — with zero terminal knowledge.

**Full version target:** `0.2.0`

### Completed Releases

#### `0.1.2` — Provider plugin system — DONE

- [x] Abstract base classes for STT and TTS providers
- [x] Moved faster-whisper and Piper behind provider interfaces
- [x] Factory selects provider by env var
- [x] Generic `VoiceSpec` base, Piper-specific `PiperVoiceSpec` extends it
- [x] `providers/README.md` contribution guide
- [x] `safe_send_str` / `safe_send_bytes` for WebSocket safety

#### `0.1.3` — Kokoro TTS — DONE

- [x] Kokoro provider implementing TTS base class
- [x] `QANTARA_TTS_PROVIDER=kokoro` selects it
- [x] 11 voice presets (US + GB English)
- [x] Warm latency: **783ms** (48% faster than Piper's 1,513ms)
- [x] Lazy pipeline caching per language code

### Next Releases

#### `0.1.4` — Backend setup experience

**Priority:** Critical — this is what makes Qantara usable by non-developers.

Right now, connecting Qantara to a backend requires knowing env vars, running multiple terminals, and understanding the adapter architecture. This must become effortless through three layers:

**Layer 1: Browser setup page**

When a user opens `http://localhost:8765`, they see a setup/welcome page instead of the raw spike UI.

The page should:
- Auto-detect available backends:
  - Check `http://localhost:11434/api/tags` — if Ollama is running, show it with available models
  - Check if an OpenClaw agent is reachable at a known port
  - Always show "Custom URL" and "Demo (mock)" options
- Let the user select a backend and configure it:
  - **Ollama**: pick a model from the detected list
  - **OpenClaw**: enter or select an agent ID
  - **Custom**: enter a backend URL that implements the session contract
  - **Demo**: no config needed, uses mock adapter for testing
- Store the selection in the browser (localStorage) so it persists across refreshes
- Show a "Start Talking" button that transitions to the voice UI
- The voice UI (current spike page) should show the active backend in a compact status bar, with an option to go back to setup

Implementation:
- [ ] New HTML page: `client/setup/index.html` — served at `/` and `/setup`
- [ ] Gateway API endpoint: `GET /api/backends` — returns detected backends
  - Probes `localhost:11434` for Ollama, returns model list
  - Probes known OpenClaw ports, returns agent list
  - Returns mock as always-available
- [ ] Gateway API endpoint: `POST /api/configure` — accepts backend selection
  - Reconfigures the active adapter at runtime (or per-session)
  - Returns confirmation with health check result
- [ ] Gateway API endpoint: `GET /api/status` — returns current backend config
- [ ] Spike page (`/spike`) updated: shows backend name in status bar, link to `/setup`
- [ ] Root route `/` serves setup page (currently serves plain text)

**Files:** `client/setup/index.html` (new), `gateway/transport_spike/server.py`, `client/transport-spike/index.html`

**Layer 2: CLI profiles**

For terminal users who prefer command-line setup:

```bash
# Auto-detect Ollama on localhost and use it
qantara --backend ollama

# Specify model
qantara --backend ollama --model qwen2.5:7b

# Use OpenClaw
qantara --backend openclaw --agent spectra

# Point at any custom backend
qantara --backend http://my-service:8080

# Demo mode (no backend needed)
qantara --backend mock
```

The gateway starts the appropriate backend bridge as a managed subprocess — no second terminal needed. If Ollama is the backend, the gateway starts the Ollama session bridge internally. If OpenClaw is selected, it starts the OpenClaw bridge.

Implementation:
- [ ] CLI entry point: `qantara` command (via `pyproject.toml` console_scripts or a `cli.py`)
- [ ] `--backend` flag with auto-detection
- [ ] Managed subprocess for backend bridges (Ollama bridge, OpenClaw bridge)
- [ ] Graceful shutdown of subprocesses on exit
- [ ] Falls back to env vars if no CLI flags provided (backward compatible)

**Files:** `cli.py` (new), `gateway/transport_spike/server.py`

**Layer 3: Config file**

For Docker Compose and persistent setups:

```yaml
# qantara.yml
backend:
  type: ollama               # ollama | openclaw | custom | mock
  url: http://localhost:11434
  model: qwen2.5:7b

voice:
  stt: faster_whisper
  tts: kokoro

server:
  host: 0.0.0.0
  port: 8765
```

Implementation:
- [ ] `qantara.yml` loader — reads from repo root or `QANTARA_CONFIG` env var
- [ ] Config values override defaults, CLI flags override config file, env vars override CLI
- [ ] Example `qantara.example.yml` in repo root

**Files:** `config.py` (new), `qantara.example.yml` (new)

**Acceptance criteria (all three layers):**
- A user opening the browser sees a setup page, picks Ollama, and starts talking — no terminal needed
- `qantara --backend ollama` starts everything in one command
- `docker compose up` with a mounted `qantara.yml` works with zero env vars
- Existing env var workflow still works (backward compatible)
- Setup page auto-detects running backends

**Effort:** 3-5 days
**Ship when:** Browser setup page works, CLI profiles work, config file loads

#### `0.1.5` — Docker one-command setup

The Docker release builds on top of the setup experience.

- [ ] `Dockerfile` for Qantara gateway + STT + TTS
- [ ] `docker-compose.yml` including Ollama with a default model
- [ ] Default `qantara.yml` in the image pointing to the Ollama service
- [ ] `docker compose up` → browser → setup page → select Ollama → speak → voice response
- [ ] README updated with Docker as the primary quickstart

**Files:** `Dockerfile`, `docker-compose.yml` (new), `qantara.yml` (new), `README.md`
**Depends on:** `0.1.4` (backend setup experience)
**Effort:** 2-3 days
**Ship when:** Fresh machine with Docker can run one command and have a voice agent

#### `0.1.6` — Contributor onboarding and launch prep

- [ ] Add GitHub topics for discoverability
- [ ] Add `CONTRIBUTING.md` referencing AGENTS.md
- [ ] Add issue templates: bug report, feature request, new provider
- [ ] Create 10 "good first issue" tickets
- [ ] Add `make test` target
- [ ] Record 30-second demo video (docker compose up → browser → voice conversation)
- [ ] Demo GIF or video linked at top of README

**Files:** `.github/ISSUE_TEMPLATE/`, `CONTRIBUTING.md`, `Makefile`, `README.md`
**Effort:** 1-2 days
**Ship when:** All items checked, demo video recorded

### Phase 1 Completion: `0.2.0` — PUBLIC LAUNCH

All of the above merged and tested. This is the version we announce.

---

## Phase 2: "Plug Into Anything"

**Goal:** Qantara becomes the standard voice layer for AI agents. Any backend, any STT, any TTS.

**Full version target:** `0.3.0`

### Early Releases

#### `0.2.1` — Vosk STT (fully offline lightweight option)

- [ ] Vosk provider implementing STT base class (`providers/stt/vosk.py`)
- [ ] `QANTARA_STT_PROVIDER=vosk` selects it
- [ ] Works fully offline with no API key
- [ ] Documented model download and setup

**Files:** `providers/stt/vosk.py` (new)
**Effort:** 1 day
**Ship when:** Vosk transcribes speech through the full pipeline

#### `0.2.2` — Chatterbox TTS (high-quality open-source voice)

- [ ] Chatterbox provider implementing TTS base class (`providers/tts/chatterbox.py`)
- [ ] `QANTARA_TTS_PROVIDER=chatterbox` selects it
- [ ] Works fully offline
- [ ] Voice quality comparison noted in docs

**Files:** `providers/tts/chatterbox.py` (new)
**Effort:** 1 day
**Ship when:** Chatterbox produces voice output through the full pipeline

#### `0.2.3` — Agent protocol v1 and tool-call support

- [ ] Protocol spec document (`protocols/agent.md`)
- [ ] Adapter base class extended with tool-call events
- [ ] Ollama adapter implements tool-call pass-through
- [ ] Browser shows "Agent is doing X..." during tool execution

**Files:** `protocols/agent.md` (new), `adapters/base.py`, `client/transport-spike/index.html`
**Effort:** 3-4 days
**Ship when:** A voice conversation can trigger a tool call and the user hears the result

#### `0.2.4` — Python SDK (`pip install qantara`)

- [ ] Package structure with `pyproject.toml`
- [ ] `from qantara import VoiceGateway` works
- [ ] 5-line example in README
- [ ] Published to PyPI (or TestPyPI first)

**Files:** `pyproject.toml`, `src/qantara/` (new)
**Effort:** 2-3 days
**Ship when:** `pip install qantara` and the 5-line example runs

### Full Phase 2 Tasks

### P2.1 — Agent protocol specification

**Priority:** Critical
**Files:** `protocols/agent.md` (new), `adapters/base.py`

Define a clean, documented protocol for connecting any AI agent to Qantara:
- Text turn submission (current)
- Streaming text response (current)
- Tool call announcement ("I'm checking your calendar...")
- Tool execution progress streaming
- Tool result summary
- Error handling in conversation
- Session context/memory interface

Acceptance criteria:
- Protocol documented in `protocols/agent.md`
- Adapter base class updated to support tool-call events
- At least one adapter (Ollama or OpenClaw) implements tool-call pass-through

### P2.2 — Additional STT providers

**Priority:** High
**Files:** `providers/stt/deepgram.py`, `providers/stt/vosk.py` (new)

Add at least two more STT options:
- **Vosk** — fully offline, lightweight, good for low-resource hardware
- **Deepgram** — cloud option for users who want it

Acceptance criteria:
- Each provider is a single file implementing the STT base class
- Selectable via `QANTARA_STT_PROVIDER` env var
- Vosk works fully offline with no API key

### P2.3 — Additional TTS providers

**Priority:** High
**Files:** `providers/tts/chatterbox.py`, `providers/tts/elevenlabs.py` (new)

Add at least two more TTS options:
- **Chatterbox** (Resemble AI) — open-source, high quality, 350M params
- **ElevenLabs** — cloud option for users who want premium voices

Acceptance criteria:
- Each provider is a single file implementing the TTS base class
- Selectable via `QANTARA_TTS_PROVIDER` env var
- Chatterbox works fully offline

### P2.4 — LangChain / CrewAI adapter

**Priority:** Medium
**Files:** `adapters/langchain_adapter.py` (new)

Create an adapter that connects Qantara to LangChain agents or CrewAI agents.

Acceptance criteria:
- A LangChain agent can receive voice input and respond via voice
- Tool calls from the agent are surfaced through the voice channel
- Example configuration documented

### P2.5 — WebRTC transport option

**Priority:** Medium
**Files:** `transports/webrtc.py` (new), `transports/websocket.py` (refactored from server.py)

Add WebRTC as an alternative transport for lower latency and NAT traversal.

Acceptance criteria:
- `QANTARA_TRANSPORT=websocket` (default, current behavior)
- `QANTARA_TRANSPORT=webrtc` uses WebRTC
- Browser client supports both
- Latency comparison documented

### P2.6 — Python SDK for embedding

**Priority:** Medium
**Files:** `sdk/` (new), `setup.py` or `pyproject.toml`

Package Qantara as a pip-installable library so developers can embed it:

```python
from qantara import VoiceGateway

gw = VoiceGateway(
    stt="faster-whisper",
    tts="kokoro",
    agent_url="http://localhost:11434"  # Ollama
)
gw.serve(port=8765)
```

Acceptance criteria:
- `pip install qantara` works
- 5-line example in README starts a voice gateway
- All existing functionality accessible through the SDK

---

## Phase 3: "The Platform"

**Goal:** Ecosystem, community, and reach.

**Full version target:** `0.4.0`

### Early Releases

#### `0.3.1` — Home Assistant add-on

- [ ] HA add-on config and Dockerfile (`integrations/homeassistant/`)
- [ ] Wyoming protocol bridge for voice commands
- [ ] Install instructions for HA users
- [ ] Tested with HA conversation agent

**Files:** `integrations/homeassistant/` (new)
**Effort:** 3-4 days
**Ship when:** HA users can install the add-on and talk to their home

#### `0.3.2` — Speech-native model passthrough

- [ ] Base class for speech-native providers (`providers/speech_native/base.py`)
- [ ] OpenAI Realtime API provider (`providers/speech_native/openai_realtime.py`)
- [ ] `QANTARA_MODE=pipeline` (default) vs `QANTARA_MODE=speech_native`
- [ ] Barge-in works in both modes

**Files:** `providers/speech_native/` (new)
**Effort:** 3-4 days
**Ship when:** A conversation runs through OpenAI Realtime with Qantara managing the session

#### `0.3.3` — Arabic voice support

- [ ] Arabic STT validation with faster-whisper (MSA + Gulf dialect accuracy report)
- [ ] Arabic TTS provider evaluation (best available open-source)
- [ ] Auto language detection in the gateway
- [ ] Arabic + English code-switching in same session

**Files:** Provider configs, `gateway/transport_spike/language_detect.py` (new)
**Effort:** 1-2 weeks
**Ship when:** A user can speak Arabic and get an Arabic voice response

#### `0.3.4` — Community plugin registry

- [ ] Registry JSON schema and initial file (`registry/providers.json`)
- [ ] GitHub Action to validate submitted providers
- [ ] README section showing available community providers
- [ ] Submission guide for contributors

**Files:** `registry/` (new), `.github/workflows/`
**Effort:** 2 days
**Ship when:** A community member can submit a provider via PR and it appears in the registry

### Full Phase 3 Tasks

### P3.1 — Home Assistant integration

**Priority:** High
**Files:** `integrations/homeassistant/` (new)

Create a Home Assistant add-on or Wyoming protocol integration.

Acceptance criteria:
- HA users can install Qantara as an add-on
- Voice commands are processed through Qantara's pipeline
- Works with HA's existing intent/conversation system

### P3.2 — SIP/telephony bridge

**Priority:** Medium
**Files:** `transports/sip.py` (new)

Add phone call support via SIP.

Acceptance criteria:
- Qantara can receive and make phone calls
- Voice pipeline works identically to browser
- Documented setup with a SIP provider

### P3.3 — Speech-native model support

**Priority:** Medium
**Files:** `providers/speech_native/openai_realtime.py`, `providers/speech_native/base.py` (new)

Support models that handle audio natively (OpenAI Realtime, Gemini audio) as an alternative to the STT→LLM→TTS pipeline.

Acceptance criteria:
- `QANTARA_MODE=pipeline` (default — STT + LLM + TTS)
- `QANTARA_MODE=speech_native` bypasses STT/TTS, sends audio directly to model
- Barge-in and turn management still work in both modes

### P3.4 — Multi-language and Arabic support

**Priority:** High for MENA differentiation
**Files:** Provider configs, language detection module

- Auto-detect input language
- Arabic STT validation (MSA + Gulf dialect)
- Arabic TTS evaluation and integration
- Code-switching support (Arabic + English in same conversation)

Acceptance criteria:
- At least Arabic and English work in the same session
- Language detection is automatic, no manual configuration

### P3.5 — Community plugin registry

**Priority:** Medium
**Files:** `registry/` (new), GitHub Actions for validation

A simple registry (JSON file or GitHub-based) where community-contributed providers and adapters are listed and discoverable.

Acceptance criteria:
- Community members can submit providers via PR
- Registry is browsable from README or docs
- CI validates that submitted providers implement the correct interface

---

## Release Cadence

```
0.1.0-alpha.2  ✅ Alpha checkpoint
0.1.2          ✅ Provider plugin system
0.1.3          ✅ Kokoro TTS (783ms warm, 48% faster than Piper)
0.1.4          ⬜ Backend setup experience (browser + CLI + config)  ← CURRENT
0.1.5          ⬜ Docker one-command setup
0.1.6          ⬜ Contributor onboarding + demo video
0.2.0          ⬜ Phase 1 complete → PUBLIC LAUNCH
0.2.1          ⬜ Vosk STT
0.2.2          ⬜ Chatterbox TTS
0.2.3          ⬜ Agent protocol + tool calls
0.2.4          ⬜ pip install qantara
0.3.0          ⬜ Phase 2 complete
0.3.1          ⬜ Home Assistant
0.3.2          ⬜ Speech-native models
0.3.3          ⬜ Arabic voice
0.3.4          ⬜ Plugin registry
0.4.0          ⬜ Phase 3 complete
```

Target: one early release every 1-2 weeks. Each release is a tagged GitHub release with changelog.

---

## Working With This Roadmap

### For Claude Code

Read `AGENTS.md` first. Pick a task from the current phase — either an early release item or a full task. Check that no one else is working on it (look at open PRs and branches). Create a branch named `release/0.1.x-description` for early releases or `phase-N/task-name` for full tasks. Follow the patterns in AGENTS.md. Open a PR when done.

### For Codex

Same as above. Each task is scoped to specific files and has clear acceptance criteria. Early release items are designed to be completable in a single Codex session. Follow the patterns in AGENTS.md. Prefer small, focused PRs over large changes.

### For Human Contributors

Start with issues labeled "good first issue." Read AGENTS.md and CONTRIBUTING.md. The provider plugin system (release `0.1.2`) is designed so that adding a new STT or TTS provider is a single-file contribution — the easiest way to get your name in the project.

### Task Status Tracking

- **Not started** — No branch or PR exists
- **In progress** — Branch exists, PR may be draft
- **In review** — PR is open and ready for review
- **Done** — PR is merged, release tagged

Check open PRs and branches before starting work to avoid conflicts.
