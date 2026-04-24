# Roadmap

Current version: `0.2.6` (first public release)

This roadmap is the single source of truth for what to build and in what order. It is designed to be read by humans, Claude Code, and Codex alike.

Each task has a clear scope, acceptance criteria, and the files involved. Tasks within a phase can be worked on in parallel unless marked as dependent.

Each phase includes **early releases** — small, shippable wins that go out as GitHub releases before the full phase is complete. This keeps the project visibly alive and gives users something new every 1-2 weeks.

---

## Phase 0: Alpha Checkpoint — COMPLETE

Version: `0.1.0-alpha.2`

- [x] Browser mic capture to gateway over WebSocket PCM
- [x] Gateway-side VAD and endpointing
- [x] faster-whisper STT integration
- [x] Piper TTS integration with sentence-chunked playback (~1.5s first audio)
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

**Goal:** Anyone can go from zero to a working local voice agent in under 60 seconds — with zero terminal knowledge. Supports Ollama and any OpenAI-compatible server out of the box, with OpenClaw kept as an advanced optional bridge for existing agent setups.

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

### Release Notes

#### `0.1.6` — OpenAI-compatible adapter — DONE

- [x] Added `adapters/openai_compatible.py`
- [x] Registered `openai_compatible` in `adapters/factory.py`
- [x] Added voice-optimized system prompt, URL normalization, `/v1` auto-detection, and SSE streaming support
- [x] Added health checks, model discovery, and bounded in-memory conversation history

#### `0.1.7` — Enhanced setup page — DONE

- [x] Added browser setup page with backend auto-detection
- [x] Added private-network URL testing and model discovery for OpenAI-compatible backends
- [x] Added advanced optional OpenClaw discovery for existing agent setups
- [x] Added browser-side configuration flow for Ollama, OpenClaw, OpenAI-compatible, custom, and demo backends

#### `0.1.8` — Clean conversation view — DONE

- [x] Shipped the single-page voice UI with avatar, captions, backend status, and debug controls
- [x] Kept the debug tools available without blocking the primary conversation flow
- [x] Landed responsive layout and browser-side voice/avatar controls

#### `0.1.9-pre` — Contributor onboarding and launch prep

- [ ] Add GitHub topics for discoverability
- [x] Add `CONTRIBUTING.md` referencing AGENTS.md
- [x] Add issue templates: bug report, feature request, new provider, new adapter
- [ ] Publish 10 "good first issue" tickets from `docs/PUBLISHING_READINESS_AUDIT.md`
- [x] Add `make test` target
- [ ] Refresh launch benchmark snapshot in README
- [ ] Demo GIF/video optional after launch
- [ ] Update README to reflect all supported backends

**Files:** `.github/ISSUE_TEMPLATE/`, `CONTRIBUTING.md`, `Makefile`, `README.md`
**Effort:** 1-2 days
**Ship when:** All required launch-prep items checked, CI green, benchmark snapshot refreshed

### Phase 1 Completion: `0.2.0` — private / pre-launch milestone

All of the above merged and tested. **Not the public launch** — the launch was shifted to `0.2.6` on 2026-04-18 so that the Tier 1 differentiation story (CLI adapters, multimodal, partial transcripts) plus Vosk + Chatterbox ship as part of the debut.

Supported backends at this milestone:
- **Ollama** — auto-detected, model selection with recommendations
- **OpenClaw** — advanced optional bridge, shown only when the host gateway is healthy
- **OpenAI-compatible** — any server with `/v1/chat/completions` (llama.cpp, vLLM, LiteLLM, Jan, LM Studio)
- **Custom URL** — manual configuration for any backend
- **Demo/Mock** — works with zero setup for testing

---

## Phase 2: "Plug Into Anything"

**Goal:** Qantara becomes the standard voice layer for AI agents. Any backend, any STT, any TTS. MCP support.

**Full version target:** `0.3.0`

Prioritization iterated twice on 2026-04-19. Post-competitive-research, MCP was briefly Tier 1 at 0.2.1. On implementation-scoping it was deferred post-launch (user call: "not worth it now") after the adapter design question surfaced tradeoffs between a simple agent-style MCP client and a richer LLM+toolbox composition pattern. MCP client + server bundled at 0.2.7 for a proper post-launch landing. **Public launch target remains `0.2.6`.** The launch narrative:

> *"Local voice for AI agents — Ollama, any OpenAI-compatible server, and an optional OpenClaw bridge. Multi-device mesh + Home Assistant (Wyoming). Interruption-safe barge-in (which livekit-agents and pipecat still get wrong). Live translation. Voice-as-API for any local app."*

Still category-of-one vs the monolith competitors (ShayneP/local-voice-ai, KokoDOS, sherpa-voice-assistant). MCP agent compatibility lands ~2-3 weeks post-launch.

### Early Releases

#### `0.2.1` — [Tier 1] Interaction polish + interruption-safe barge-in

**Why:** Validated community pain — interruption deadlocks (livekit/agents #5359 5s hang, pipecat #4260 dropped frames, pipecat #1694) are the #1 production bug in the voice-AI ecosystem; partial transcripts + clear "thinking/speaking/listening" state are the visible detail that separates "toy" from "product" in a demo. Competitors ship none of these turnkey. This release lands all three together as the foundation other Tier 1 items build on.

**Bounded partial transcripts:**
- [ ] Extend `providers/stt/base.py` with optional `async transcribe_partial(pcm_bytes) -> str` (default raises NotImplementedError; providers opt in)
- [ ] `providers/stt/faster_whisper.py` implements it with trailing 2-3s window (no `vad_filter` — faster path). Stable-prefix merge so ghosted text doesn't jitter
- [ ] Background tick task in `gateway/transport_spike/speech.py` — ~400ms cadence, started on `speech_start_detected`, stopped on `speech_end_detected`
- [ ] New `partial_transcript_ready` event; client renders ghosted beneath mic indicator, cleared on `final_transcript_ready`
- [ ] `QANTARA_STT_STREAMING` env — auto-detect default (on for GPU/MPS, off for CPU-only). Vosk-based partials ship in 0.2.4 as the proper CPU path

**Explicit state machine:**
- [ ] Formalize `idle | listening | thinking | speaking | interrupted` states on the `Session` class in `runtime.py` with transitions logged through the existing event sink
- [ ] `session_state_changed` event (source: `session`) carries old/new state + ms-since-last-state
- [ ] Browser UI renders state via avatar glow + caption ("Thinking about your question…" / "Listening…" / "Speaking…"). Reuses existing avatar state infrastructure from PR #5

**Interruption-safe barge-in:**
- [ ] State-preserving cancellation in `gateway/transport_spike/speech.py` — when VAD detects user speech mid-TTS, cancel playback *and* snapshot the adapter's in-flight turn state (partial assistant text) so resume is possible
- [ ] TTS queue drain fix — no dropped leading audio on resumed turns (pipecat #4260 equivalent bug)
- [ ] Explicit `turn_interrupted` event with `partial_text` + `resumable` flags so the UI can render graceful state
- [ ] Benchmark harness: cut-off-mid-sentence test that fails today on livekit-agents and pipecat — ours must pass. Recording of this comparison links from the README at launch.

**`assistant_activity` event (foundation for 0.2.7 MCP):**
- [ ] Schema in `schemas/EVENT_TIMELINE.md` — fields: `activity_type` (`tool_call` / `reading_files` / `searching` / `thinking`), `summary` (string, one-sentence), `progress` (optional 0..1)
- [ ] Non-spoken strip in the UI, capped at last N activities per turn. Adapters can emit these today (no-op for mock/ollama/openclaw/openai; becomes useful when MCP lands at 0.2.7)

**Files:** `providers/stt/base.py`, `providers/stt/faster_whisper.py`, `gateway/transport_spike/speech.py`, `gateway/transport_spike/runtime.py` (state machine on Session), `gateway/transport_spike/websocket_api.py`, `schemas/EVENT_TIMELINE.md`, `client/transport-spike/index.html`, `tests/test_partial_transcripts.py` (new), `tests/test_session_state.py` (new), `tests/test_interruption.py` (new)
**Effort:** 1 week
**Ship when:** partial transcript appears within ~500ms of speaking and updates smoothly without flicker; state transitions fire correctly across a full turn cycle; cutting the agent off mid-sentence cleanly cancels and preserves partial state for the next turn; the benchmark harness passes the two public livekit/pipecat interruption-failure cases

#### `0.2.2` — [Tier 1] Multi-device mesh with Wyoming compatibility — DONE

Shipped 2026-04-19. 22 tasks landed across 5 phases: mesh foundation, election, runtime integration, Wyoming bridge, and polish.

**Why:** #1 unmet need across both research passes. HA users, r/selfhosted, and the LocalLLaMA "planning to build a voice assistant" thread all describe the same scenario: "two speakers in two rooms, I want the closest one to respond and not both." HA ships per-satellite wake word but couples everything to its own stack. No competitor solves the general case. Shipping a Wyoming-protocol-compatible mesh gets Qantara immediate adoption from the HA community while also serving anyone running two Qantara nodes on a LAN.

**Peer discovery + routing:**
- [x] `gateway/mesh/discovery.py` — mDNS/Zeroconf service advertisement under `_qantara._tcp.local`. Each node publishes name, capabilities (STT/TTS/adapters available), and current audio RMS
- [x] Election protocol: when multiple nodes hear the same utterance start, the node with the highest RMS claims the turn; others mute. Short (~150ms) race window then commit
- [x] `QANTARA_MESH_ROLE` env — `speaker-only`, `mic-only`, `full`. A phone could be `mic-only` with TTS routed to desktop
- [x] Cross-node session continuity: the claiming node runs STT+adapter+TTS locally by default; explicit "speak reply on node X" flag for the speaker-routing case

**Wyoming protocol compatibility:**
- [x] `gateway/mesh/wyoming_bridge.py` — expose Qantara as a Wyoming satellite so HA's assistant pipeline can use it as a mic/speaker endpoint
- [x] Docs: "Qantara in Home Assistant" section with setup snippet ([docs/HOMEASSISTANT.md](../docs/HOMEASSISTANT.md))

**UI + ops:**
- [x] Setup page shows discovered peers + their capabilities
- [ ] Per-turn indicator: which node caught the mic, which node spoke the reply (deferred to 0.3.x; `turn_deferred_to_peer` event fires but no visual badge on the voice overlay yet)
- [x] `make doctor --mesh` reports discovery state + latencies

**Files:** `gateway/mesh/discovery.py` (new), `gateway/mesh/wyoming_bridge.py` (new), `gateway/mesh/election.py` (new), `gateway/transport_spike/runtime.py` (mesh lifecycle), `client/setup/index.html` (peer panel), `docs/HOMEASSISTANT.md` (new), `tests/test_mesh_election.py` (new)
**Effort:** 2-3 weeks (largest Tier 1 item; do not underestimate)
**Ship when:** two Qantara nodes on the same LAN correctly elect a single responder for a spoken utterance; a third node joins/leaves cleanly mid-session; HA can discover a Qantara node as a Wyoming satellite and route a pipeline through it

---

The items below complete the public-launch bundle and the post-launch roadmap.

#### `0.2.3` — [Tier 1] Voice-as-API (HTTP/WS for any local app)

**Why:** Second strongest wedge in both research passes. Expands Qantara's addressable audience from "people who want a voice assistant" to "every developer with a local app that could benefit from voice." An Obsidian plugin, a terminal tool, a Home Assistant automation — anyone can POST to Qantara and get streamed TTS or submit audio for STT + agent reply. Reinforces the "voice transport, not monolith app" positioning.

- [ ] `POST /api/v1/speak` — accepts `{text, voice_id?, route?}`, streams back audio/pcm or audio/wav. `route` can target a specific mesh peer from 0.2.2
- [ ] `POST /api/v1/transcribe` — accepts audio body, returns text. Streams partials if `?stream=true`
- [ ] `POST /api/v1/converse` — accepts `{text | audio, backend?, session_id?}`, runs the full STT→adapter→TTS loop, streams events back as SSE
- [ ] `WS /api/v1/stream` — bi-directional streaming variant for long-lived integrations
- [ ] Auth via existing `QANTARA_AUTH_TOKEN` (already landed in commit `d4d15ed`)
- [ ] Example clients: 3-line shell (`curl`), 5-line Python, 5-line Node, one Obsidian plugin snippet
- [ ] Rate limit + audit log per token

**Files:** `gateway/transport_spike/http_api.py` (new endpoints), `docs/VOICE_API.md` (new), `docs/examples/clients/*` (new), `tests/test_voice_api.py` (new)
**Effort:** 4-6 days
**Ship when:** `curl -X POST localhost:8765/api/v1/speak -d '{"text":"hello"}' | play` works; a 10-line example app using `/converse` runs end-to-end

#### `0.2.4` — Vosk STT + Live translation bundle

**Vosk STT** (CPU-friendly streaming):
- [ ] `providers/stt/vosk.py` implementing both `transcribe` and `transcribe_partial`
- [ ] `QANTARA_STT_PROVIDER=vosk` selects it; auto-select on CPU-only hosts to use Vosk for partials even when faster-whisper is the final engine
- [ ] Fully offline, no API key

**Live translation** (promoted from 0.3.3):
- [ ] `gateway/transport_spike/language_detect.py` — detect input language from the final transcript (faster-whisper already returns language; expose it)
- [ ] Translation mode toggle in UI: "speak in X, hear in Y" — defaults to English ↔ Arabic (aligned with the project's name), user-selectable pairs
- [ ] Adapter prompt augmentation: when translation mode is on, wrap the system prompt with "Reply in {target_language}"
- [ ] TTS voice auto-routes to the target language's Kokoro voice pack
- [ ] Scope explicitly limited: supported pairs at launch = EN↔AR, EN↔ES, EN↔FR, EN↔ZH (matches Kokoro's language coverage). N-to-N matrix is 0.3.x work

**Files:** `providers/stt/vosk.py` (new), `providers/stt/factory.py`, `gateway/transport_spike/language_detect.py` (new), `gateway/transport_spike/speech.py` (mode routing), `client/transport-spike/index.html` (mode picker), `tests/test_translation_mode.py` (new)
**Effort:** 4-5 days total (Vosk ~1-2d, translation ~3d)
**Ship when:** Vosk streaming works on a CPU-only VM; a user can toggle EN→AR and say "hello" and hear "مرحبا" (or the reply in Arabic) from the agent

#### `0.2.5` — Chatterbox TTS

Launch voice upgrade. Ships before 0.2.6 so the benchmark snapshot and public docs reflect the expressive voice path.

- [ ] `providers/tts/chatterbox.py` implementing TTS base class; fully offline
- [ ] `QANTARA_TTS_PROVIDER=chatterbox` selects it; made the default for the launch Docker image

**Files:** `providers/tts/chatterbox.py` (new)
**Effort:** 1-2 days

#### `0.2.6` — PUBLIC LAUNCH

This is the version we announce. Everything from 0.2.1 through 0.2.5 merged, tested, benchmarked, and documented.

- [ ] Benchmark snapshot refreshed in README and `docs/BENCHMARKS.md`
- [ ] README comparison table refreshed against ShayneP/local-voice-ai, KokoDOS, sherpa-voice-assistant (and Pipecat/LiveKit for context)
- [ ] `docs/FIRST_PUBLIC_RELEASE_NOTES_DRAFT.md` finalized with the launch positioning line
- [ ] `docs/RELEASE_CHECKLIST.md` executed
- [ ] GitHub release tagged, topics set, "good first issue" tickets live
- [ ] Benchmark numbers per OS (macOS, Linux, Windows) on at least one reference box each
- [ ] Head-to-head barge-in regression notes vs livekit/pipecat refreshed in `docs/BENCHMARKS.md`

**Files:** `README.md`, `docs/BENCHMARKS.md`, `docs/FIRST_PUBLIC_RELEASE_NOTES_DRAFT.md`, `docs/RELEASE_CHECKLIST.md`, `CHANGELOG.md`
**Effort:** 3-4 days
**Ship when:** all prior 0.2.x items merged, CI green on all three OSes, benchmarks refreshed, and launch copy is ready

#### `0.2.7` — MCP voice client + server (postponed from 0.2.1)

Landed together post-launch as a single MCP release. **Client:** talk to any MCP-enabled agent (HASS MCP, `claude mcp serve`, custom tool servers). **Server:** expose Qantara's own voice capabilities as MCP tools so any MCP-compatible agent elsewhere can drive Qantara remotely.

**MCP client adapter:**
- [ ] `adapters/mcp_client.py` against `mcp==1.27.*` — stdio + streamable-HTTP transports. Initial scope = agent-style: invoke a named chat tool with the transcript, stream the result via `progress_callback` → `assistant_activity` events, final text → `assistant_text_final`
- [ ] `runtime.py::_create_binding` learns `mcp` backend kind
- [ ] `QANTARA_MCP_TRANSPORT` (stdio|http) + `QANTARA_MCP_COMMAND` / `QANTARA_MCP_URL` / `QANTARA_MCP_CHAT_TOOL` env config
- [ ] Setup page tile for "Any MCP server" with `tools/list` probe
- [ ] Reference preset configs in `docs/examples/mcp/` (HASS MCP, `claude mcp serve`, filesystem-MCP, hello-world fixture)
- [ ] Known cancellation race with SDK #2416 worked around via task-cancel + assertion swallow

**MCP server (expose voice as tools):**
- [ ] `mcp_server.py` using the same SDK
- [ ] Tools: `voice_session_start`, `voice_speak`, `voice_interrupt`, `voice_set_voice`, `voice_get_status`, `voice_get_transcript`, `voice_set_translation_mode`
- [ ] Resources: `qantara://voices`, `qantara://avatars`, `qantara://sessions/{id}/status`, `qantara://mesh/peers`
- [ ] Streamable HTTP transport for remote agents; stdio for local. Audio stays on WS — MCP is control-plane only

**Deferred to later (not in 0.2.7):** the LLM+toolbox composition pattern where an existing LLM adapter is augmented with MCP tool-use routing. Needs 0.2.3 voice-as-API event flow finalized first. Targeted at 0.3.x.

**Files:** `adapters/mcp_client.py` (new), `mcp_server.py` (new), `adapters/factory.py`, `gateway/transport_spike/runtime.py`, `client/setup/index.html`, `docs/examples/mcp/*.json` (new), `tests/test_mcp_client.py` (new), `tests/test_mcp_server.py` (new)
**Effort:** 2-3 weeks
**Ship when:** (1) a conversation with a locally-running MCP server (HASS MCP or `claude mcp serve`) works end-to-end, with tool-call progress rendering as `assistant_activity` events; (2) Claude Desktop can connect to Qantara's MCP server, start a session, and make it speak

#### `0.2.8` — Agent protocol v1 and tool-call formalization

- [ ] Protocol spec document (`protocols/agent.md`) — formalizes `assistant_activity` / `session_state_changed` / `turn_interrupted` events introduced across 0.2.1-0.2.2
- [ ] Adapter base class extensions for richer tool-call metadata (progress, confidence, parameters)
- [ ] Browser shows tool-call parameters inline on hover

**Files:** `protocols/agent.md` (new), `adapters/base.py`, `client/transport-spike/index.html`
**Effort:** 3-4 days

#### `0.2.9` — Python SDK (`pip install qantara`)

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

#### `0.3.2` — Speech-native adapter interface

**Why:** The industry is moving from cascaded STT→LLM→TTS to end-to-end speech-native models (OpenAI Realtime, Gemini Live, Moshi, Kyutai, MiniCPM-o). Today Qantara's adapter contract is text-shaped (`submit_user_turn(transcript)` / `assistant_text_delta`), which forces these models through their text endpoints and loses prosody, emotion, paralinguistic cues, and mid-word interruption. A speech-native adapter type keeps Qantara relevant as the gateway for *any* voice model, not just cascade stacks.

**What changes:**
- [ ] New `SpeechNativeAdapter` base alongside `RuntimeAdapter` — audio-shaped contract: `stream_user_audio(pcm_frames)` and yields `{type: "audio_delta", pcm, sample_rate}` alongside existing text events
- [ ] Gateway `speech.py` branches on adapter mode: cascade path (current) vs passthrough (skip STT and TTS)
- [ ] Browser client plays adapter-forwarded PCM without change — same binary frame protocol
- [ ] VAD + barge-in still live in the gateway (transport concern, not model concern) — cancel propagates to adapter via existing `cancel_turn`
- [ ] Reference implementations: OpenAI Realtime API, Gemini Live, MiniCPM-o (via local inference)
- [ ] `QANTARA_ADAPTER=openai_realtime` / `gemini_live` / `minicpm_o` selects them

**Files:** `adapters/base.py` (extend), `adapters/openai_realtime.py`, `adapters/gemini_live.py`, `adapters/minicpm_o.py`, `gateway/transport_spike/speech.py`
**Effort:** 1-2 weeks
**Ship when:** A 4o-realtime conversation runs end-to-end through Qantara with barge-in working and first-audio latency under 400ms

#### `0.3.3` — Arabic voice deepening + N-to-N translation matrix

Basic EN↔AR translation shipped in 0.2.5. This item extends it:

- [ ] Arabic STT dialect validation (MSA + Gulf + Levantine + Egyptian)
- [ ] Arabic TTS prosody tuning beyond Kokoro's default
- [ ] Seamless code-switching mid-utterance (EN→AR→EN in one sentence)
- [ ] N-to-N translation matrix across all Kokoro-supported languages
- [ ] Identity-aware translation preference per speaker (pairs with 0.3.x identity work)

**Files:** Provider configs, extensions to `gateway/transport_spike/language_detect.py`
**Effort:** 1-2 weeks

#### `0.3.4` — Identity-aware sessions (voice fingerprinting)

**Why:** Deferred from Tier 1 consideration on 2026-04-19. Needs real-user validation before shipping blind — post-launch is the right time to land it once households are actually using Qantara and tell us they want per-speaker context.

- [ ] `providers/identity/pyannote.py` — on-device voice fingerprinting via pyannote, no cloud
- [ ] SQLite per-speaker store for profile + conversation context
- [ ] `session_state_changed` gains `speaker_id`; adapters receive it via `turn_context`
- [ ] UI: per-speaker avatar colors, opt-in enrollment flow
- [ ] Privacy: fingerprints are local-only, deletable, never transmitted

**Files:** `providers/identity/pyannote.py` (new), `gateway/transport_spike/identity.py` (new), `gateway/transport_spike/speech.py`, `client/transport-spike/index.html`
**Effort:** 2-3 weeks

#### `0.3.5` — Screenshot + voice multimodal

**Why:** Deferred from Tier 1 on 2026-04-19. Real feature, just not the launch wedge — community signal is weaker than multi-device/MCP/barge-in. The OpenAI-compatible multimodal message shape also needs a broader refactor (history is string-based today) that's better done after launch.

- [ ] Browser `getDisplayMedia` + "capture screen" button
- [ ] `turn_context.image_data_uri` propagates through the submit path
- [ ] `openai_compatible.py` builds multimodal `content` blocks when present
- [ ] MCP client (0.2.1) gains image support via MCP's `content` array
- [ ] Visible "📷 attached" chip in the UI

**Files:** `client/transport-spike/index.html`, `adapters/openai_compatible.py`, `adapters/mcp_client.py`, `gateway/transport_spike/speech.py`, `gateway/transport_spike/websocket_api.py`
**Effort:** 4-6 days (includes the message-shape refactor)

#### `0.3.6` — Ambient announcement bus

**Why:** Emerged from the novel-features brainstorm. HA and any local app can emit events; Qantara picks the right room/device/voice and ducks active playback. Natural complement to 0.2.3's multi-device mesh.

- [ ] `POST /api/v1/announce` accepting `{text, priority, zone?, voice?, duck?}`
- [ ] Integration with 0.2.3 mesh for room selection
- [ ] Audio ducking during active conversation playback
- [ ] HASS automation examples

**Effort:** 1 week

#### `0.3.7` — Per-turn hybrid routing (local ↔ cloud)

- [ ] Policy adapter that classifies a turn as "simple" (local) or "hard" (cloud escalation)
- [ ] Visible badge in UI — green for local, yellow for cloud
- [ ] User override per turn
- [ ] Respects the existing privacy framing — cloud is always opt-in per request

**Effort:** 1 week

#### `0.3.8` — Multi-participant voice rooms

**Why:** Two or more humans + one AI in a single session with speaker attribution and interruption fairness. Builds on 0.3.4 identity.

- [ ] Speaker-diarized turn routing
- [ ] Interruption fairness policy (AI doesn't always yield to the loudest)
- [ ] Per-speaker transcript lanes in the UI

**Effort:** 2-3 weeks

#### `0.3.9` — Community plugin registry

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
0.1.6          ✅ OpenAI-compatible adapter
0.1.7          ✅ Enhanced setup page
0.1.8          ✅ Clean conversation view
0.1.9-pre      ✅ Contributor onboarding
0.2.1          ✅ [Tier 1] Interaction polish + interruption-safe barge-in
0.2.2          ✅ [Tier 1] Multi-device mesh + Wyoming-compatible (HA) + mobile UX
0.2.4          ✅ Multilingual assistant + directional + live conversation translator (EN/AR/ES/FR/JA)
0.2.5          ✅ Chatterbox TTS (expressive voice)
0.2.6          ✅ PUBLIC LAUNCH — first public GitHub release
0.2.7          ⬜ MCP client + server (postponed from 0.2.1)
0.2.8          ⬜ Agent protocol v1 + tool-call formalization
0.2.9          ⬜ pip install qantara
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
