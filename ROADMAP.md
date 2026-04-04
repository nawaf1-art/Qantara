# Roadmap

Current version: `0.1.0-alpha.2`

This roadmap is the single source of truth for what to build and in what order. It is designed to be read by humans, Claude Code, and Codex alike.

Each task has a clear scope, acceptance criteria, and the files involved. Tasks within a phase can be worked on in parallel unless marked as dependent.

Each phase includes **early releases** — small, shippable wins that go out as GitHub releases before the full phase is complete. This keeps the project visibly alive and gives users something new every 1-2 weeks.

---

## Phase 0: Alpha Checkpoint — COMPLETE

Version: `0.1.0-alpha.2`

Everything below is done:

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

## Phase 1: "It Just Works" — NEXT

**Goal:** Anyone can go from zero to a working local voice agent in under 60 seconds.

**Full version target:** `0.2.0`

### Early Releases

#### `0.1.1` — Cleanup and contributor onboarding

The quickest release. No new features — just make the repo ready for others.

- [ ] Add GitHub topics: `voice-ai`, `voice-agent`, `local-first`, `tts`, `stt`, `ollama`, `speech-to-speech`, `real-time`, `open-source`
- [ ] Add `CONTRIBUTING.md` referencing AGENTS.md with the provider contribution pattern
- [ ] Add issue templates: bug report, feature request, new provider (`.github/ISSUE_TEMPLATE/`)
- [ ] Create 10 "good first issue" tickets with specific file references
- [ ] Clean up any remaining TODO comments in source files
- [ ] Add a `make test` target (even if it just runs a smoke test)

**Files:** `.github/ISSUE_TEMPLATE/`, `CONTRIBUTING.md`, `Makefile`
**Effort:** 1-2 hours
**Ship when:** All items checked

#### `0.1.2` — Provider plugin system

Refactor STT and TTS so adding a new one is a single-file contribution. This unblocks all future provider work.

- [ ] Abstract base class for STT providers (`providers/stt/base.py`)
- [ ] Abstract base class for TTS providers (`providers/tts/base.py`)
- [ ] Move faster-whisper into `providers/stt/faster_whisper.py`
- [ ] Move Piper into `providers/tts/piper.py`
- [ ] Factory selects provider by `QANTARA_STT_PROVIDER` / `QANTARA_TTS_PROVIDER`
- [ ] `providers/README.md` — "How to add a provider" guide
- [ ] Update AGENTS.md with new provider patterns

**Files:** `providers/` (new), `gateway/transport_spike/server.py`
**Effort:** 1-2 days
**Ship when:** Existing STT/TTS works unchanged through new plugin system

#### `0.1.3` — Kokoro TTS

Add the community's favorite local TTS. Immediate quality upgrade.

- [ ] Kokoro provider implementing TTS base class (`providers/tts/kokoro.py`)
- [ ] `QANTARA_TTS_PROVIDER=kokoro` selects it
- [ ] Auto-download or clear model setup instructions
- [ ] First-audio latency measured and added to README
- [ ] Piper remains the default fallback

**Files:** `providers/tts/kokoro.py` (new)
**Depends on:** `0.1.2` (plugin system)
**Effort:** 1 day
**Ship when:** Kokoro produces voice output through the full pipeline

#### `0.1.4` — Docker one-command setup

The big one for Phase 1. This is what we launch with.

- [ ] `Dockerfile` for Qantara gateway + STT + TTS
- [ ] `docker-compose.yml` including Ollama with a default model
- [ ] `docker compose up` → browser → speak → voice response
- [ ] No env vars required for default setup
- [ ] README updated with Docker as the primary quickstart

**Files:** `Dockerfile`, `docker-compose.yml` (new), `README.md`
**Depends on:** `0.1.3` (Kokoro as default TTS in Docker image)
**Effort:** 2-3 days
**Ship when:** Fresh machine with Docker can run one command and have a voice agent

### Full Phase 1 Tasks

### P1.1 — Docker packaging

**Priority:** Critical
**Files:** `Dockerfile`, `docker-compose.yml` (new), `Makefile`

Create a single `docker compose up` that starts:
- Qantara gateway with STT + TTS
- Ollama backend with a default model (qwen2.5:7b or similar small model)
- Browser client served at `http://localhost:8765`

Acceptance criteria:
- Clone repo → `docker compose up` → open browser → speak → get voice response
- No env vars required for default setup
- Works on Linux x86_64 with Docker installed
- README documents the one-command setup

### P1.2 — Kokoro TTS integration

**Priority:** High
**Files:** `providers/tts/kokoro.py` (new), `gateway/transport_spike/server.py`
**Depends on:** P1.3

Add Kokoro (82M param, Apache 2.0) as a TTS provider alongside Piper.

Acceptance criteria:
- `QANTARA_TTS_PROVIDER=kokoro` selects Kokoro
- `QANTARA_TTS_PROVIDER=piper` keeps current behavior (default)
- First audio chunk latency measured and documented
- Kokoro model auto-downloads or has clear setup instructions

### P1.3 — Provider plugin system

**Priority:** High
**Files:** `providers/stt/base.py`, `providers/tts/base.py`, `providers/stt/faster_whisper.py`, `providers/tts/piper.py`, `providers/tts/kokoro.py`, `providers/README.md` (all new)

Refactor STT and TTS into a clean plugin system:
- Abstract base class for STT providers
- Abstract base class for TTS providers
- Each provider is a single file implementing the base class
- Factory selects provider by `QANTARA_STT_PROVIDER` / `QANTARA_TTS_PROVIDER` env var
- `providers/README.md` documents how to add a new provider (copy template, implement 3 methods)

Acceptance criteria:
- Existing faster-whisper and Piper work unchanged after refactor
- Adding a new provider requires only: one new file + one line in factory
- AGENTS.md is updated with the new pattern

### P1.4 — Demo video and launch materials

**Priority:** High
**Files:** `README.md`, assets

Record a 30-second terminal + browser demo:
- Show `docker compose up`
- Show browser opening
- Show a voice conversation happening
- No narration needed — just screen recording

Acceptance criteria:
- GIF or video linked at the top of README.md
- README updated with docker compose instructions as the primary quickstart

### P1.5 — GitHub discoverability

**Priority:** Medium
**Files:** GitHub repo settings, `.github/ISSUE_TEMPLATE/` (new)

- Add repo topics
- Create issue templates: bug report, feature request, new provider
- Create 10 "good first issue" tickets with specific file references and context
- Add `CONTRIBUTING.md` with the provider contribution pattern

Acceptance criteria:
- GitHub shows topics on repo page
- At least 10 open issues labeled "good first issue"
- CONTRIBUTING.md exists and references AGENTS.md

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
0.1.0-alpha.2  ← you are here
0.1.1          ← contributor onboarding (days away)
0.1.2          ← provider plugin system
0.1.3          ← Kokoro TTS
0.1.4          ← Docker one-command setup
0.2.0          ← Phase 1 complete, public launch
0.2.1          ← Vosk STT
0.2.2          ← Chatterbox TTS
0.2.3          ← Agent protocol + tool calls
0.2.4          ← pip install qantara
0.3.0          ← Phase 2 complete
0.3.1          ← Home Assistant
0.3.2          ← Speech-native models
0.3.3          ← Arabic voice
0.3.4          ← Plugin registry
0.4.0          ← Phase 3 complete
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
