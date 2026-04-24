# Changelog

All notable changes to Qantara are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches `1.0.0`. Until then, minor versions may include breaking changes — see the release notes on each tag.

## [Unreleased]

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
- README and launch docs now reflect the `0.2.6-dev.1` pre-launch state.

### Fixed
- Arabic-script transcripts override short-utterance language fallback, so brief Arabic turns stay Arabic.
- Session state stays active until queued TTS finishes, avoiding premature `idle` while playback is still running.
- `/api/configure` now validates request body and URL safety before unloading the previously configured model.
- `/api/translation_mode` now honors `QANTARA_AUTH_TOKEN`.
- Gateway HTTP tests no longer depend on port `19120`, avoiding collisions with a live bridge.

## [0.2.4] - 2026-04-20

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

## [0.2.5] - 2026-04-20

### Added
- Chatterbox TTS provider (expressive neural voice, optional dep under `.[chatterbox]` extra).
- `expressiveness` voice transform (0.0 → 1.0) routed to Chatterbox's `exaggeration` parameter. Piper and Kokoro ignore it.
- `/api/tts` endpoint reporting the active engine plus available engines.
- Setup-page TTS engine picker; voice-mode "Voice Feeling" slider that auto-hides when the active voice does not support expressiveness.
- `chatterbox_warm` voice registered in `identity/voice-registry/voices.json`.

## [0.2.2] - 2026-04-20

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

## [0.1.9-pre] — 2026-04-18 — Pre-launch polish

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

[Unreleased]: https://github.com/nawaf1-art/Qantara/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/nawaf1-art/Qantara/compare/v0.2.5...v0.2.4
[0.2.5]: https://github.com/nawaf1-art/Qantara/compare/v0.2.2...v0.2.5
[0.2.2]: https://github.com/nawaf1-art/Qantara/compare/v0.1.9-pre...v0.2.2
[0.1.9-pre]: https://github.com/nawaf1-art/Qantara/releases/tag/v0.1.9-pre
