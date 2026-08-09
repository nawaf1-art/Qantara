# Changelog

All notable changes to Qantara are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches `1.0.0`. Until then, minor versions may include breaking changes — see the release notes on each tag.

## [0.3.1] - 2026-08-09

### Added
- Reusable release consistency, package-content, and clean-install smoke checks for wheel and source artifacts.
- A manual tag-only draft-release workflow that produces checksums, SPDX SBOM output, validation evidence, and GitHub provenance attestations from the same validated build.
- Public privacy, governance, support, release-process, and architectural-debt documentation, plus structured issue forms and CODEOWNERS.

### Changed
- CI now uses immutable Action commit SHAs, least-privilege permissions, concurrency controls, a lightweight cross-platform test extra, dependency review, and a base-runtime vulnerability audit.
- The Python source version is `0.3.1`; wheel artifacts now include public protocol and schema resources, while source-only utilities are documented explicitly.
- Docker uses digest-pinned Python and Ollama images, hash-checked Python dependencies, a hash-pinned spaCy model wheel, a non-root runtime user, and a build context that excludes both common virtual-environment names.
- Public documentation now uses one pre-1.0 status vocabulary and separates verified behavior from planned work and historical benchmark data.

### Fixed
- Default event output no longer writes transcripts, assistant text, tool parameters, or credentials to stdout; managed bridge output is opt-in and gateway-only credentials are removed from child environments.
- Origin checks now compare host and port, and a LAN-aware Host guard rejects public or malformed authorities unless explicitly allowlisted.
- WebSocket control messages, PCM frames, Voice API text, generated output, backend JSON, MCP progress queues, and incremental stream lines now have explicit bounds.
- Timed-out OpenClaw discovery and Piper processes are killed and reaped; local outbound probes and adapters do not inherit proxy settings or follow redirects.
- Backend URL validation rejects embedded credentials, public status payloads sanitize URLs, and HTTP responses include browser security and no-store headers.
- The CLI now actually configures the OpenAI-compatible adapter when given an HTTP backend URL.

### Upgrade Notes
- Custom internal DNS names outside the built-in loopback/private/LAN-name policy must be listed in `QANTARA_ALLOWED_HOSTS`.
- Set `QANTARA_BRIDGE_LOG_OUTPUT=1` only when bridge stdout/stderr is needed for local diagnostics; review that output before sharing it.
- GitHub Release artifacts are published from the protected `v0.3.1` tag; PyPI remains out of scope for this release.

## [0.3.0] - 2026-07-30

### Changed
- Corrected the release line after the Python SDK milestone: Qantara now uses `0.3.0` as the canonical current version.
- Consolidated the Python SDK, Voice-as-API, Ollama compatibility, stream-correctness, audit, and dependency-hardening work under the `0.3.0` platform milestone.
- Preserved the published `v0.2.10` and `v0.2.12` tags as immutable historical compatibility points.

### Fixed
- Mesh shutdown no longer hangs when a peer connection is accepted but its handler has not yet registered. `MeshServer.stop()` now marks itself closing before snapshotting open connections, so a handler scheduled after that point exits instead of blocking in `readline()`. This closes the intermittent `macos-latest` / Python 3.12 CI failure in `test_stop_completes_while_peer_connection_is_open`.

### Upgrade Notes
- Apart from the mesh shutdown fix above, `0.3.0` matches `0.2.12` at runtime; the rest of the release is version and release metadata.
- Users pinned to `v0.2.10` or `v0.2.12` are not required to change immediately. New installations and downstream references should use `v0.3.0`. Anyone running the mesh should prefer `v0.3.0`.

## [0.2.12] - 2026-07-24

### Added
- Ollama compatibility guide covering the native and OpenAI-compatible API paths, thinking-model behavior, current model recommendations, and the Ollama `0.32.3` validation target.
- Regression coverage for fragmented/coalesced NDJSON and SSE frames, split UTF-8 Arabic, reasoning-only responses, malformed bridge requests, and current Ollama model metadata.

### Changed
- Updated the default Ollama model from `qwen2.5` to the current, compact `qwen3.5:2b`; the setup page now prioritizes Qwen 3.5, Qwen 3, and Gemma 3 models.
- Pinned the Docker Compose Ollama services to the validated `0.32.3` image instead of the floating `latest` tag.
- Disabled Ollama thinking by default on the native voice bridge to reduce first-audio latency. Hidden reasoning remains available as an opt-in but is never sent to TTS.
- Refreshed the pinned Python/ML stack, including aiohttp 3.14, MCP 1.28, CPU-only PyTorch 2.13, Wyoming 1.10, and zeroconf 0.150.
- Wyoming discovery now reports the actual Qantara package version instead of the stale `0.2.2` value.

### Fixed
- Ollama NDJSON parsing no longer assumes one HTTP chunk per JSON object, so split records, coalesced records, and multibyte text are preserved.
- The OpenAI-compatible SSE parser now uses incremental UTF-8 decoding and never promotes `reasoning`, `reasoning_content`, or `thinking` fields into spoken assistant output.
- The generic session-gateway stream parser now preserves multibyte text split across network chunks.
- Cancelling a direct OpenAI-compatible stream now acknowledges the cancellation even when closing the HTTP response raises a connection error, and rolls the interrupted user turn out of history.
- Native Ollama and OpenAI-compatible streams now fail clearly on reasoning-only or empty responses instead of completing a silent turn.
- The Ollama session bridge rejects malformed JSON shapes with a 400 response and closes its HTTP client if connection setup fails.
- Includes the July platform-audit fixes for translator PCM framing, converse timeout/session recovery, barge-in during turn acceptance, control-speech state, auth-lock UI behavior, and Docker build-context exclusions.

### Security
- Upgraded direct and transitive dependencies to patched releases, kept the universal lock compatible with Python 3.11, and pinned the Docker speech stack to the CPU-only PyTorch index, avoiding unintended CUDA package installation.

## 0.2.11 - Unreleased (superseded by 0.2.12)

### Added
- Voice-as-API was prepared on the `0.2.11` branch but never tagged. It ships in `0.2.12`: `POST /api/v1/speak` (text → WAV/PCM audio), `POST /api/v1/transcribe` (WAV or raw-PCM16 audio → text + language), and `POST /api/v1/converse` (text turn → SSE stream of agent-protocol events, with optional `session_id` continuity). Auth uses `QANTARA_AUTH_TOKEN`; examples live in `docs/examples/clients/`; see [docs/VOICE_API.md](docs/VOICE_API.md).

### Fixed
- Mesh server shutdown no longer hangs while peers are still connected (found during real-network verification of `QANTARA_MESH_TOKEN`).

## [0.2.10] - 2026-06-10

### Added
- Python SDK: `pip install qantara` installs the gateway as a package; `from qantara import VoiceGateway` exposes `create_app()` for embedding and `run()` for standalone serving. Base install needs only `aiohttp`; local speech, mesh/Home Assistant, and MCP ship as `qantara[speech]`, `qantara[mesh]`, and `qantara[mcp]` extras.

### Changed
- `providers.tts` and `providers.stt` package imports no longer eagerly import concrete providers (and their heavy optional dependencies such as numpy); provider selection was already lazy in the factory.

## [0.2.9] - 2026-06-10

### Added
- Agent protocol v1 spec at `protocols/agent.md`, formalizing the adapter/gateway/browser event contract (`assistant_activity`, `session_state_changed`, `turn_interrupted`, and the adapter stream events).
- Richer tool-call metadata on `assistant_activity`: optional `tool_name`, `parameters`, and `confidence` fields, built via `adapters.base.make_activity_event()`, re-validated by the gateway before forwarding, and shown by the browser as an inline tooltip on hover. The MCP adapter now reports its chat tool name.
- Optional mesh frame authentication via `QANTARA_MESH_TOKEN`: when set, every mesh frame carries an HMAC-SHA256 signature and nodes drop unsigned, tampered, or wrong-token frames. See [docs/MESH.md](docs/MESH.md).

### Security
- Hardened the security boundary from the 2026-05-30 audit: SSRF allowlist now rejects link-local/unspecified/reserved/multicast addresses and unwraps IPv4-mapped IPv6; DNS-rebinding pinning for `/api/configure` and `/api/test-mcp`; `/api/test-url` no longer follows redirects; Origin/CSRF guard middleware on `/ws` and state-changing requests (`QANTARA_ALLOWED_ORIGINS`); the MCP server refuses non-loopback HTTP binding without `QANTARA_MCP_SERVER_ALLOW_INSECURE=1`.
- Mesh election now matches peer RMS by node and recency instead of session id (fixes the split-brain where every node claimed every utterance), and untrusted LAN frames are validated (bounded ids, finite RMS, bounded Wyoming payload lengths).

### Fixed
- Cleaned up Qantara lifecycle regressions around OpenAI-compatible adapter turn bookkeeping, active browser session snapshot pruning, and backend reconfiguration model unload ordering.
- Barge-in no longer depends on adapter cooperation: after `cancel_turn`, the gateway force-cancels the in-flight turn task once a bounded grace window (`QANTARA_TURN_CANCEL_GRACE_MS`, default 750 ms) expires, so a wedged backend cannot pin the session.
- The OpenClaw deep health check now terminates its CLI subprocess on timeout (`QANTARA_OPENCLAW_HEALTH_TIMEOUT`, default 25 s) instead of leaking it.
- Adapter and bridge session stores are now bounded with LRU eviction (`QANTARA_OPENAI_MAX_SESSIONS`, `QANTARA_MCP_MAX_SESSIONS`, `QANTARA_BACKEND_MAX_SESSIONS`; default 64) and per-session turn records are capped, fixing unbounded memory growth in long-running gateways.
- Background asyncio tasks (bridge health waits, bridge log pumps, bridge shutdowns, OpenClaw cancel escalation) are now retained until done and log their exceptions instead of being silently garbage-collected.
- faster-whisper lazy model initialization is now lock-guarded so concurrent transcribe calls cannot load the model twice.
- Browser clients release audio resources on page teardown: the translate client stops microphone tracks and closes its AudioContext, and the voice client closes the playback AudioContext on `pagehide`.

## [0.2.8] - 2026-04-30

### Added
- MCP client adapter for agent-style chat tools over stdio or streamable HTTP (`mcp==1.27.*`), including progress-to-`assistant_activity` forwarding.
- MCP server (`mcp_server.py`) exposing Qantara browser voice control tools over stdio or streamable HTTP.
- Protected gateway control endpoints under `/api/control/voice/*` for active-session status, session-start guidance, speaking text, transcript/timeline reads, interrupting playback, changing voice, and changing translation mode.
- MCP resources for voices, languages, avatars, active sessions, per-session status/transcript, and mesh peers.
- Setup-page MCP backend tile with a protected `tools/list` probe for configured stdio servers and private/loopback HTTP MCP URLs.
- Reference MCP config examples under `docs/examples/mcp/`.

### Changed
- Adapter activity events now flow through the gateway to the browser activity strip.
- Docker Compose passes MCP client environment variables through to the gateway container.

### Upgrade and Test Notes
- Upgrade from a prior checkout with `git pull`, then rebuild Docker with `docker compose up --build` or refresh the native virtualenv requirements.
- Test the stable path by opening `http://localhost:8765`, choosing Demo or OpenAI-Compatible, granting microphone access, and confirming playback plus barge-in.
- MCP support is new in this release. Automated stdio and streamable-HTTP smoke tests passed, but a real desktop MCP client and physical browser voice session should still be validated in each target environment.
- See [docs/QUICKSTART.md](docs/QUICKSTART.md), [docs/FEATURES.md](docs/FEATURES.md), and [docs/MCP.md](docs/MCP.md).

## [0.2.7] - 2026-04-28

### Added
- Browser-friendly auth unlock flow for `QANTARA_AUTH_TOKEN` using `/api/auth/status`, `/api/auth/login`, `/api/auth/logout`, and an HttpOnly local session cookie.
- Docker Compose pass-through for `QANTARA_AUTH_TOKEN`, `QANTARA_ADMIN_TOKEN`, mesh, and Wyoming variables.
- Gateway container healthcheck for `/api/status`.

### Changed
- First-run Docker documentation now reflects the measured larger disk footprint of the Qantara image and local LLM pull.
- Docker uses the multilingual `small` Whisper model by default, matching the public multilingual launch claim.
- Mesh and Wyoming bind to loopback by default; LAN exposure now requires explicit `QANTARA_MESH_HOST=0.0.0.0` or `QANTARA_WYOMING_HOST=0.0.0.0`.
- Public docs now describe Kokoro as running through the `kokoro` Python package instead of implying direct ONNX runtime usage.

### Fixed
- Docker runtime dependency lock now includes the mesh discovery dependencies (`ifaddr`, `wyoming`, and `zeroconf`) required by the gateway container.
- `QANTARA_AUTH_TOKEN` comparison now uses constant-time comparison and rejects configured tokens shorter than 24 characters.
- `QANTARA_AUTH_TOKEN` now protects warmup, test URL probing, backend discovery, LAN discovery scan, and mesh status endpoints in addition to WebSocket and configuration endpoints.
- `/api/test-url` now connects to resolved private/loopback addresses while preserving the original Host header, reducing DNS-rebinding exposure during setup probing.
- Launch-language TTS availability now selects voices by matching locale, so English Kokoro voices no longer advertise Japanese TTS availability.

## [0.2.6] - 2026-04-24

### Added
- Arabic Piper voice routing for `ar_JO-kareem-medium`, including a 1.3x Arabic baseline rate.
- Transient Qantara voice-turn context prompts for OpenAI-compatible, Ollama bridge, and OpenClaw bridge backends.
- Issue templates for new provider and new adapter proposals.
- Internal launch-ready drafts for 10 good-first-issue tickets.
- Repeatable launch benchmark script for barge-in and TTS latency.
- Public publication-readiness audit, cleanup report, security audit, install guide, config guide, developer onboarding guide, release checklist, and first-release notes draft.
- Voice registry schema validation test.

### Changed
- Browser TTS status now includes the active voice id for easier voice-routing QA.
- OpenClaw setup is now an advanced optional path: hidden unless the host gateway is healthy, and labeled as optional when detected.
- Setup's no-backend state now ignores the manual OpenAI-compatible card unless a server is auto-detected.
- Public launch docs now treat demo media as optional and use benchmark refresh as the required evidence path.
- Removed tracked private-development notes from the public docs surface and sanitized local examples.
- README and launch docs now reflect the `0.2.6` first public release state.

### Fixed
- Arabic-script transcripts override short-utterance language fallback, so brief Arabic turns stay Arabic.
- Session state stays active until queued TTS finishes, avoiding premature `idle` while playback is still running.
- `/api/configure` now validates request body and URL safety before unloading the previously configured model.
- `/api/translation_mode` now honors `QANTARA_AUTH_TOKEN`.
- Gateway HTTP tests no longer depend on port `19120`, avoiding collisions with a live bridge.
- Public CI tests no longer depend on local Piper voice files or OS-specific closed-port timing.
- Speaker-mode barge-in now uses a stricter active-turn gate to reduce false interruption from TTS leaking into the microphone.

## 0.2.4 - 2026-04-20

### Added
- Multilingual assistant — Whisper swapped to `small` (multilingual), auto language detection per turn, same-language reply.
- Directional translator mode (opt-in) — fixed source/target pair for language-learning and fixed-language output.
- Live conversation translator — dedicated `/translate` page, half-duplex push-to-talk, split-view transcripts.
- `/api/languages` and `/api/translation_mode` endpoints.
- Language badge in voice-mode transcript log.
- Spanish + French Piper voices registered (`es_ES-davefx-medium`, `fr_FR-siwis-medium`); fetch script at `scripts/fetch_piper_voices.sh`.
- Translation directive plumbed through session state → adapter per-turn context → openai-compatible system-prompt prefix (transient, not persisted in history).
- Backend-compat warning in setup page for non-Latin translation targets on smaller local backends.

### Changed
- `STTProvider.transcribe` now returns `STTResult(text, language, language_probability)`; callers updated. Backward-compatible: `str(result)` returns the text.
- Default Whisper model changed from `base.en` to `small` (~460MB). Override via `QANTARA_WHISPER_MODEL`.

## 0.2.5 - 2026-04-20

### Added
- Chatterbox TTS provider (expressive neural voice, optional dep under `.[chatterbox]` extra).
- `expressiveness` voice transform (0.0 → 1.0) routed to Chatterbox's `exaggeration` parameter. Piper and Kokoro ignore it.
- `/api/tts` endpoint reporting the active engine plus available engines.
- Setup-page TTS engine picker; voice-mode "Voice Feeling" slider that auto-hides when the active voice does not support expressiveness.
- `chatterbox_warm` voice registered in `identity/voice-registry/voices.json`.

## 0.2.2 - 2026-04-20

### Added
- **Multi-device mesh on `_qantara._tcp.local.`** — peer discovery via mDNS, RMS-based single-responder election (~150ms window, lexicographic tie-break), role-aware routing (`full`/`mic-only`/`speaker-only`). Controlled via `QANTARA_MESH_ROLE`. Implementation split across `gateway/mesh/{protocol,peer_registry,election,transport,discovery,controller,wyoming_bridge}.py`. Session-level integration: `Session.mesh_should_respond` + `maybe_run_election_and_claim` + `turn_deferred_to_peer` event gate turn submit on election outcome.
- **Wyoming-protocol satellite on `_wyoming._tcp.local.`** port 10700 — Home Assistant auto-discovers Qantara as a voice satellite. Controlled via `QANTARA_WYOMING_ENABLED`. `SessionConnector` routes HA audio chunks through STT → adapter → TTS and streams the reply back as Wyoming audio-chunk frames.
- **HTTP surface:** `/api/mesh/peers` + `/api/mesh/status` endpoints; setup-page panel shows live peers with auto-refresh.
- **Ops:** `make doctor --mesh` reports discovery state + per-peer TCP latency.
- **Docs:** `docs/MESH.md`, `docs/HOMEASSISTANT.md`, `schemas/MESH_PROTOCOL.md`.
- **Dependencies:** `wyoming==1.8.0`, `zeroconf==0.148.0`.
- README now states explicitly that Qantara ships with no telemetry and no outbound connections to Qantara-controlled servers, and includes a head-to-head comparison table against Pipecat, LiveKit Agents, Home Assistant Voice, and the Ollama-voice-script tier.
- Competitive research and public-positioning notes informed the pre-launch roadmap.
- ROADMAP Tier 1 pre-launch priorities spanning 0.2.1–0.2.3: interaction polish + interruption-safe barge-in, multi-device mesh with Wyoming compatibility, and voice-as-API for any local app. Launch bundle adds Vosk + live translation (0.2.4), Chatterbox TTS (0.2.5), and the public launch itself (0.2.6). MCP client + server combined at 0.2.7 post-launch. Public-launch target moved from 0.2.0 to 0.2.6.
- Model warmup between setup and voice mode: new `/api/warmup` endpoint preloads the configured Ollama or OpenAI-compatible model; setup page shows a warmup overlay with elapsed counter.

### Changed
- Hardened the gateway control surface: `/api/configure` now rejects public URLs, `/ws` and `/api/configure` optionally require `QANTARA_AUTH_TOKEN`, and `/api/admin/runtime` is disabled unless `QANTARA_ADMIN_TOKEN` is set.
- Removed deterministic canned replies from the Ollama bridge so every turn now goes through the configured Ollama model.
- `gateway/transport_spike/requirements.in` now imports the full runtime stack from `ops/docker/requirements.in`, keeping `make spike-install` aligned with the Docker image.
- Docker now publishes the gateway on `127.0.0.1` by default via `QANTARA_DOCKER_BIND`, while still allowing explicit LAN exposure.
- Tightened wording around TTS to describe the current behavior accurately as sentence-chunked streaming playback.
- **Mobile UX pass** after live Pixel Chrome testing: `env(safe-area-inset-*)` on voice overlay, `100dvh` alongside `100vh` fallback, `touch-action: manipulation` on interactive elements, 16px font-size floor on inputs, `.vc-close` bumped to 44×44 (Apple HIG tap-target floor).
- **VAD RMS thresholds** lowered for mobile AGC: `VAD_START_RMS: 0.045→0.02`, `VAD_STOP_RMS: 0.012→0.006`, `PLAYBACK_BARGE_IN_START_RMS: 0.09→0.04`.
- **Weak-speech filter** thresholds lowered twice based on live logs: `MIN_AVG_RMS` 0.04 → 0.015 → 0.006; `MIN_PEAK_RMS` 0.085 → 0.04 → 0.018.
- Setup-page probe label: OpenAI-Compatible row now shows "manual config" (green) during auto-detect probes instead of flashing "not found".

### Fixed
- Hardened line-buffer handling for the session-gateway and OpenAI-compatible streaming parsers so partial chunks are reassembled correctly.
- Replaced the discovery scanner's `8.8.8.8` UDP probe with a local `getaddrinfo()` lookup and loopback fallback.
- Surfaced managed bridge stdout/stderr through Python logging so bridge startup failures are diagnosable.
- Added visible microphone-permission guidance in the browser client and removed the Google Fonts dependency.
- **Backend switch in `/api/configure`** now actually applies to returning sessions. Previously `register_session()` pinned the binding from a stale per-client snapshot, so switching backend from the setup page had no effect on the next `/spike` reconnect. Snapshot now carries voice prefs only; binding always follows the current default.

## 0.1.9-pre — 2026-04-18 — Pre-launch polish

### Added
- `SECURITY.md` with a disclosure policy pointing at GitHub's private vulnerability reporting flow.
- `docs/SUPPLY_CHAIN.md` documenting what Qantara downloads, who verifies integrity, and how to run an air-gapped install.
- `CODE_OF_CONDUCT.md` adopting Contributor Covenant 2.1.
- `CONTRIBUTING.md` with setup, workflow, extension patterns, and security disclosure.
- `docs/TROUBLESHOOTING.md` covering first-day install and runtime issues.
- Initial launch runbook and name-availability notes.
- `.github/workflows/test.yml` — CI with ruff lint plus test matrix across Ubuntu, macOS, and Windows on Python 3.11 and 3.12.
- `.github/ISSUE_TEMPLATE/` (bug report, feature request) and `PULL_REQUEST_TEMPLATE.md`.
- `pyproject.toml` with ruff configuration and `.pre-commit-config.yaml`.
- `make doctor` target (`scripts/doctor.py`) — environment check for Python, aiohttp, port availability, Docker, backend CLIs, Piper voices, TLS.
- `make smoke-test` target (`scripts/smoke_test.py`) — end-to-end gateway smoke test against a mock adapter.
- End-to-end tests for turn lifecycle state transitions and `/api/test-url` rate limiting.
- Test for graceful bridge-process shutdown on `runtime.close()`.
- Rate limiting on `/api/test-url` (8 requests per 10 seconds per client IP).

### Changed
- Split `gateway/transport_spike/server.py` (1428 lines) into five focused modules: `common.py`, `runtime.py`, `http_api.py`, `websocket_api.py`, `speech.py`. The server entry point is now a 76-line wiring shim.
- Moved planning and experiment docs out of the repo root so first-time visitors see user-facing docs at the top level.
- Pinned exact dependency versions with SHA256 hashes via `pip-compile` for both the gateway and Docker requirement sets.
- Expanded ROADMAP 0.3.2 into a full speech-native adapter plan covering OpenAI Realtime, Gemini Live, and MiniCPM-o.
- README now distinguishes Qantara from speech-native models and heavy frameworks, documents Docker first-run size (~5 GB, 5–10 min), and flags that OpenClaw is host-only in Docker.
- Unified voice metadata behind `providers/voice_registry.py` with a single `identity/voice-registry/voices.json` as source of truth for Piper and Kokoro.

### Fixed
- 39 lint issues surfaced by ruff: unused imports, deprecated typing imports, missing `raise … from`, unused variables, import ordering.
- Version references aligned on `0.1.9-pre` across `VERSION`, `AGENTS.md`, `README.md`, and `ROADMAP.md`.

[Unreleased]: https://github.com/nawaf1-art/Qantara/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/nawaf1-art/Qantara/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/nawaf1-art/Qantara/compare/v0.2.12...v0.3.0
[0.2.12]: https://github.com/nawaf1-art/Qantara/compare/v0.2.10...v0.2.12
[0.2.10]: https://github.com/nawaf1-art/Qantara/compare/v0.2.9...v0.2.10
[0.2.9]: https://github.com/nawaf1-art/Qantara/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/nawaf1-art/Qantara/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/nawaf1-art/Qantara/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/nawaf1-art/Qantara/releases/tag/v0.2.6
