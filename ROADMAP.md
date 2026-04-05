# Roadmap

Current version: `0.1.5`

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

**Goal:** Anyone can go from zero to a working local voice agent in under 60 seconds — with zero terminal knowledge. Supports Ollama, OpenClaw, and any OpenAI-compatible server out of the box.

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
- [x] Kokoro synthesis offloaded to `asyncio.to_thread()` for non-blocking event loop

#### `0.1.4` — Backend setup experience — DONE

- [x] Browser setup page at `/` and `/setup` with auto-detection
- [x] Gateway API: `GET /api/backends`, `POST /api/configure`, `GET /api/status`
- [x] Managed backend bridge subprocesses (Ollama, OpenClaw)
- [x] CLI entry point (`cli.py`) with `--backend`, `--model`, `--agent` flags
- [x] Config file loader (`config.py`) with `qantara.yml` support
- [x] Spike page backend status bar with link to setup

#### `0.1.5` — Docker one-command setup — DONE

- [x] Dockerfile with Kokoro as default TTS
- [x] docker-compose.yml with Ollama + model pull + backend + gateway
- [x] `QANTARA_PORT` env var for host port override
- [x] Setup page as entry point after `docker compose up`
- [x] README updated with Docker as primary quickstart

### In Review

#### Avatar overhaul — PR #5 (branch: `avatar/dicebear-adventurer`)

- [x] GSAP replaced with zero-dependency vanilla JS animation
- [x] SVG face with audio-amplitude-driven mouth morphing (quadratic bezier lerp)
- [x] Eye blink animation (random interval, occasional double blink)
- [x] Breathing animation (sine wave translateY)
- [x] State-aware glow rings (idle/listening/thinking/speaking)
- [x] 9 color presets with customizable skin/hair/accent
- [x] Speaking-state hold (800ms) to prevent flickering
- [x] Playback state debounce (600ms)
- [x] Synthetic 440Hz tone fallback removed from server
- [x] Speech speed default reset to 1.00x

**Status:** Needs merge after remaining code review items are addressed.

### Next Releases

#### `0.1.6` — OpenAI-compatible adapter

**Priority:** Critical — this is the single highest-leverage change for backend coverage.

A new adapter that connects directly to any server exposing `/v1/chat/completions`. Covers llama.cpp, vLLM, LiteLLM, LocalAI, Jan.ai, LM Studio, and Ollama's OpenAI mode — with no bridge process needed.

Implementation:
- [ ] New adapter: `adapters/openai_compatible.py`
  - Implements the existing adapter interface (`start_or_resume_session`, `submit_user_turn`, `stream_assistant_output`, `cancel_turn`, `check_health`)
  - Speaks `/v1/chat/completions` with SSE streaming directly
  - Maintains conversation history in-memory (messages array with truncation)
  - Lists models via `/v1/models`
  - Configurable: base URL, model, API key (optional), system prompt
- [ ] Register in `adapters/factory.py` as `openai_compatible`
- [ ] Voice-optimized default system prompt (short, conversational, no markdown)
- [ ] Robust SSE parser that handles all server quirks:
  - Both `data: ` and `data:` prefix (with/without space)
  - `delta.content` AND `delta.reasoning_content` (vLLM)
  - `role` repeated in every chunk (Ollama)
  - `data: [DONE]` as authoritative stream-end signal
  - Both Ollama (`{"error": "string"}`) and OpenAI (`{"error": {"message": "..."}}`) error formats
- [ ] URL normalization: strip trailing slash, strip `/v1`, auto-prepend `http://`
- [ ] Auto-detect `/v1` prefix (try with, then without)
- [ ] Connection validation via `/v1/models` before first turn
- [ ] Generous first-token timeout (30s for cold model loading)
- [ ] Conversation history truncation (keep last N turns + system prompt for 4K-8K context models)
- [ ] API key passed as `"not-needed"` for local servers (SDK requires non-empty)
- [ ] Tool calling disabled by default (breaks Ollama streaming)

**Files:** `adapters/openai_compatible.py` (new), `adapters/factory.py`
**Effort:** 2-3 days
**Ship when:** `QANTARA_ADAPTER=openai_compatible QANTARA_OPENAI_BASE_URL=http://localhost:8080 make spike-run` works with llama.cpp

#### `0.1.7` — Enhanced setup page

**Priority:** Critical — makes the setup experience dummy-proof for all backends.

Three major improvements to the setup page:

**A. OpenAI-compatible backend option**

- [ ] New backend card: "Any OpenAI-Compatible Server"
- [ ] URL input with placeholder showing common ports (8080, 8000, 1337, 1234)
- [ ] Auto-detect servers on common ports in parallel (2s timeout each):
  - Port 11434: Ollama (already done)
  - Port 8080: llama.cpp / LocalAI (`GET /health` then `GET /v1/models`)
  - Port 8000: vLLM (`GET /v1/models`)
  - Port 1337: Jan.ai (`GET /v1/models`)
  - Port 1234: LM Studio (`GET /v1/models`)
- [ ] "Test" button with specific diagnostic error messages
- [ ] Model dropdown populated from `/v1/models` response
- [ ] Subtitle: "llama.cpp, vLLM, LiteLLM, Jan, LM Studio, and more"

**B. Ollama improvements**

- [ ] Model filter/search for large model lists (30+ models)
- [ ] "Recommended for voice" section at top with 2-3 suggested models
- [ ] Model size shown in human-readable format (GB) next to each name
- [ ] Note: "Smaller models (3-7B) respond faster for voice conversations"
- [ ] Handle "Ollama running but no models": show inline `ollama pull` instructions
- [ ] Use `<optgroup>` to group models by family

**C. OpenClaw agent discovery**

- [ ] New API endpoint: `GET /api/backends/openclaw`
  - Runs `openclaw agents list --json` to get agent names
  - Runs `openclaw health --json` to check gateway status
  - Returns: `{ installed, gateway_running, agents: [{id, name}] }`
- [ ] Agent selection as radio buttons (not blind text input)
- [ ] Show agent name only (no model — model is set by the agent, not Qantara)
- [ ] "Test Agent" button that runs a quick test turn
- [ ] When gateway is not running: show `openclaw gateway run` instruction
- [ ] When OpenClaw is not installed: show `npm install -g openclaw` instruction
- [ ] Profile selection if multiple profiles detected

**D. First-run experience**

- [ ] "Getting Started" panel shown when no backends are detected
- [ ] Step-by-step Ollama install instructions with copy-pasteable commands
- [ ] Background polling every 5 seconds — auto-detect when backend comes online
- [ ] Grey dots for "not detected" (not red — red means error)
- [ ] "Scan Again" button
- [ ] "Configure Manually" fallback link

**E. Error handling**

- [ ] Connection refused → "Cannot reach [url]. Is the server running?"
- [ ] Timeout → "Server not responding. It may be starting up — try again."
- [ ] 200 but no models → "Connected but no models installed. Run `ollama pull llama3.2`."
- [ ] 401 → "API key required. Enter it below."
- [ ] SSL on localhost → "SSL error. For local servers, use http://."

**Files:** `client/setup/index.html`, `gateway/transport_spike/server.py`
**Effort:** 2-3 days
**Ship when:** All backend types auto-detect and configure without user knowing any env vars or ports

#### `0.1.8` — Contributor onboarding and launch prep

- [ ] Add GitHub topics for discoverability
- [ ] Add `CONTRIBUTING.md` referencing AGENTS.md
- [ ] Add issue templates: bug report, feature request, new provider, new adapter
- [ ] Create 10 "good first issue" tickets
- [ ] Add `make test` target
- [ ] Record 30-second demo video (docker compose up → browser → voice conversation)
- [ ] Demo GIF or video linked at top of README
- [ ] Update README to reflect all supported backends

**Files:** `.github/ISSUE_TEMPLATE/`, `CONTRIBUTING.md`, `Makefile`, `README.md`
**Effort:** 1-2 days
**Ship when:** All items checked, demo video recorded

### Phase 1 Completion: `0.2.0` — PUBLIC LAUNCH

All of the above merged and tested. This is the version we announce.

Supported backends at launch:
- **Ollama** — auto-detected, model selection with recommendations
- **OpenClaw** — auto-detected agents, one-click selection
- **OpenAI-compatible** — any server with `/v1/chat/completions` (llama.cpp, vLLM, LiteLLM, Jan, LM Studio)
- **Custom URL** — manual configuration for any backend
- **Demo/Mock** — works with zero setup for testing

---

## Phase 2: "Plug Into Anything"

**Goal:** Qantara becomes the standard voice layer for AI agents. Any backend, any STT, any TTS. MCP support.

**Full version target:** `0.3.0`

### Early Releases

#### `0.2.1` — MCP voice server (control-plane)

Optional MCP server exposing voice capabilities as tools. Any MCP-compatible agent (Claude, GPT, LangChain, CrewAI) can connect and use Qantara's voice.

- [ ] MCP server using official Python SDK (`mcp` package)
- [ ] Tools: `voice_session_start`, `voice_speak`, `voice_interrupt`, `voice_set_voice`, `voice_get_status`, `voice_get_transcript`
- [ ] Resources: `qantara://voices`, `qantara://avatars`, `qantara://sessions/{id}/status`
- [ ] Streamable HTTP transport for remote agents
- [ ] stdio transport for local development
- [ ] Audio stays on WebSocket — MCP handles control plane only

**Files:** `mcp_server.py` (new)
**Effort:** 2-3 days
**Ship when:** Claude Desktop can connect to Qantara's MCP server and make it speak

#### `0.2.2` — Vosk STT (fully offline lightweight option)

- [ ] Vosk provider implementing STT base class (`providers/stt/vosk.py`)
- [ ] `QANTARA_STT_PROVIDER=vosk` selects it
- [ ] Works fully offline with no API key

**Files:** `providers/stt/vosk.py` (new)
**Effort:** 1 day

#### `0.2.3` — Chatterbox TTS (high-quality open-source voice)

- [ ] Chatterbox provider implementing TTS base class (`providers/tts/chatterbox.py`)
- [ ] `QANTARA_TTS_PROVIDER=chatterbox` selects it
- [ ] Works fully offline

**Files:** `providers/tts/chatterbox.py` (new)
**Effort:** 1 day

#### `0.2.4` — Agent protocol v1 and tool-call support

- [ ] Protocol spec document (`protocols/agent.md`)
- [ ] Adapter base class extended with tool-call events
- [ ] Browser shows "Agent is doing X..." during tool execution

**Files:** `protocols/agent.md` (new), `adapters/base.py`, `client/transport-spike/index.html`
**Effort:** 3-4 days

#### `0.2.5` — Python SDK (`pip install qantara`)

- [ ] Package structure with `pyproject.toml`
- [ ] `from qantara import VoiceGateway` works
- [ ] 5-line example in README

**Files:** `pyproject.toml`, `src/qantara/` (new)
**Effort:** 2-3 days

---

## Phase 3: "The Platform"

**Goal:** Ecosystem, community, and reach.

**Full version target:** `0.4.0`

### Early Releases

#### `0.3.1` — Home Assistant add-on

- [ ] HA add-on via Wyoming protocol integration
- [ ] Voice commands processed through Qantara's pipeline

**Files:** `integrations/homeassistant/` (new)
**Effort:** 3-4 days

#### `0.3.2` — Speech-native model passthrough

- [ ] Support for OpenAI Realtime API and Gemini audio as providers
- [ ] `QANTARA_MODE=pipeline` (default) vs `QANTARA_MODE=speech_native`
- [ ] Barge-in works in both modes

**Files:** `providers/speech_native/` (new)
**Effort:** 3-4 days

#### `0.3.3` — Arabic voice support

- [ ] Arabic STT validation (MSA + Gulf dialect)
- [ ] Arabic TTS evaluation and integration
- [ ] Auto language detection
- [ ] Arabic + English code-switching in same session

**Files:** Provider configs, `gateway/transport_spike/language_detect.py` (new)
**Effort:** 1-2 weeks

#### `0.3.4` — Community plugin registry

- [ ] Registry JSON schema for community-contributed providers and adapters
- [ ] GitHub Action for validation
- [ ] Submission guide

**Files:** `registry/` (new), `.github/workflows/`
**Effort:** 2 days

---

## Release Cadence

```
0.1.0-alpha.2  ✅ Alpha checkpoint
0.1.2          ✅ Provider plugin system
0.1.3          ✅ Kokoro TTS (783ms warm)
0.1.4          ✅ Backend setup experience (browser + CLI + config)
0.1.5          ✅ Docker one-command setup
               🔄 Avatar overhaul (PR #5 — in review)
0.1.6          ⬜ OpenAI-compatible adapter  ← NEXT
0.1.7          ⬜ Enhanced setup page (all backends dummy-proof)
0.1.8          ⬜ Contributor onboarding + demo video
0.2.0          ⬜ Phase 1 complete → PUBLIC LAUNCH
0.2.1          ⬜ MCP voice server (control-plane)
0.2.2          ⬜ Vosk STT
0.2.3          ⬜ Chatterbox TTS
0.2.4          ⬜ Agent protocol + tool calls
0.2.5          ⬜ pip install qantara
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
