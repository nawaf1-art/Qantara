# Session Handoff

Date: 2026-04-28

## Current State

Qantara is public on GitHub at `https://github.com/nawaf1-art/Qantara` from the clean `public-main` history. Do not publish the old private git history.

This handoff covers the original public-release readiness pass, the 2026-04-26 post-public hardening pass based on the read-only external audit in `docs/audits/QANTARA-end-to-end-readonly-audit-2026-04-25.md`, and the 2026-04-28 local release checkpoint.

Hardening update pushed to GitHub `main`: `6d2e028 fix: harden auth and LAN defaults`.

GitHub Actions for that commit passed:

- `Tests`: passed across Ubuntu, macOS, and Windows on Python 3.11 and 3.12
- `Release Drafter`: passed

Latest local Docker validation stack:

- loopback URL: `http://127.0.0.1:9877`
- started with a disposable 24-character test token
- services: `qantara-ollama`, `qantara-backend`, and `qantara-gateway` are healthy
- host port `8765` was already occupied by a separate local `python3` process, so this checkpoint used `QANTARA_PORT=9877`

Important: `docs/audits/` is currently untracked and contains local-machine details from the external audit. Do not add it to a public commit unless it is deliberately sanitized first.

## What Was Requested

The user asked for Qantara to be made ready for public GitHub publication, then asked to handle the external audit findings and prepare the work for handover.

The project objective is unchanged:

- Qantara is a standalone, local-first real-time voice gateway.
- It is for Ollama, local LLM engines, and local AI agents.
- It is a voice layer, not an agent framework.
- Local LLMs remain with Qantara and the user's local runtime.

## What Was Fixed In The Original Readiness Pass

- Removed tracked `docs/internal/`.
- Added the public documentation set:
  - `docs/README.md`
  - `docs/PUBLISHING_READINESS_AUDIT.md`
  - `docs/REPOSITORY_CLEANUP_REPORT.md`
  - `docs/SECURITY_PUBLICATION_AUDIT.md`
  - `docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md`
  - `docs/CONFIGURATION.md`
  - `docs/DEVELOPER_ONBOARDING.md`
  - `docs/RELEASE_CHECKLIST.md`
  - `docs/FIRST_PUBLIC_RELEASE_NOTES_DRAFT.md`
  - `docs/SESSION_HANDOFF.md`
  - `.env.example`
- Updated `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `.gitignore`, and `qantara.example.yml`.
- Sanitized public-facing wording away from the old OpenClaw-first framing.
- Fixed Docker runtime dependency lock for mesh/Wyoming dependencies.
- Ran and documented a clean Docker validation after the dependency-lock fix.

## What Was Fixed In This Hardening Pass

- Hardened `QANTARA_AUTH_TOKEN`:
  - rejects configured tokens shorter than 24 characters
  - uses constant-time token comparison
  - supports browser login through `/api/auth/login`
  - stores browser unlock state in an HttpOnly local cookie
  - keeps bearer-token auth for API clients
- Protected additional endpoints when `QANTARA_AUTH_TOKEN` is set:
  - `/ws`
  - `/api/configure`
  - `/api/translation_mode`
  - `/api/warmup`
  - `/api/test-url`
  - `/api/backends`
  - `/api/backends/stream`
  - `/api/discovery/scan`
  - `/api/mesh/peers`
  - `/api/mesh/status`
- Added auth status/login/logout routes:
  - `GET /api/auth/status`
  - `POST /api/auth/login`
  - `POST /api/auth/logout`
- Updated the setup page and voice/translate clients so browser users can unlock Qantara instead of needing impossible WebSocket/EventSource auth headers.
- Added a startup warning when the gateway binds to a non-loopback host with no `QANTARA_AUTH_TOKEN`.
- Hardened backend URL probing:
  - public URLs are rejected
  - dotted public hostnames are fast-rejected unless they are clearly local suffixes
  - `/api/test-url` connects to resolved private/loopback IPs while preserving the original Host header
- Changed mesh and Wyoming defaults to loopback:
  - `QANTARA_MESH_HOST` default is now `127.0.0.1`
  - `QANTARA_WYOMING_HOST` default is now `127.0.0.1`
  - LAN mesh/Wyoming now requires explicit `0.0.0.0`
- Updated Docker Compose:
  - gateway healthcheck for `/api/status`
  - `QANTARA_WHISPER_MODEL=small` to match multilingual launch behavior
  - pass-through for auth, admin, mesh, and Wyoming environment variables
- Corrected public docs:
  - Qantara wording emphasizes Ollama, local LLMs, and local AI agents
  - LAN docs include token examples
  - Kokoro is described as running through the `kokoro` Python package, not direct ONNX runtime
  - avatar wording now says amplitude-driven mouth motion, not phoneme lipsync
  - mesh/Wyoming docs state the plaintext trusted-LAN boundary
- Fixed launch-language TTS availability and voice routing to select voices by matching locale. Kokoro English voices now advertise English availability, not Japanese availability.

## Validation Run

Passed on 2026-04-28 from `public-main` commit `c1fe21875b7aac106924a4c5d6a959ade8478874` plus the local language-catalog fix:

```bash
make test
/home/nawaf/.local/bin/ruff check .
git diff --check
./.venv/bin/python -m compileall -q adapters gateway providers scripts tests cli.py config.py discovery
make smoke-test
make doctor
./.venv/bin/python scripts/bench_launch.py --arabic
docker compose config -q
QANTARA_AUTH_TOKEN=<24-char-test-token> QANTARA_PORT=9877 docker compose up --build -d
curl http://127.0.0.1:9877/api/status
curl http://127.0.0.1:9877/setup/index.html
curl -o /tmp/qantara-unauth-backends.json -w '%{http_code}' http://127.0.0.1:9877/api/backends
curl -c /tmp/qantara-cookie \
  -H 'Content-Type: application/json' \
  -d '{"token":"<24-char-test-token>"}' \
  http://127.0.0.1:9877/api/auth/login
curl -b /tmp/qantara-cookie http://127.0.0.1:9877/api/backends
curl http://127.0.0.1:9877/api/tts
curl http://127.0.0.1:9877/api/languages
```

Results:

- `ruff`: passed
- unit tests: 162 passed
- compileall: passed
- whitespace check: passed
- smoke test: passed
- doctor: ready; warned only that port `8765` is in use
- benchmark snapshot: barge-in median `0.12 ms`, Piper English median `1532.32 ms`, Piper Arabic median `1770.37 ms`
- Docker Compose config: passed
- Docker build: passed using cached layers
- Docker stack health: `qantara-ollama`, `qantara-backend`, and `qantara-gateway` healthy
- setup page: loaded and rendered the auth panel plus Start Talking UI
- auth smoke: unauthenticated `/api/backends` returned `401`, login returned `200`, authenticated `/api/backends` returned backend options
- `/api/status`, `/api/tts`, and `/api/languages`: returned valid JSON
- `/api/languages`: after the local language-catalog fix, Kokoro reports English available through `af_heart` and Japanese unavailable until a real Japanese voice is installed
- Docker WebSocket/backend/TTS smoke: passed through `ws://127.0.0.1:9877/ws`; a real backend turn returned TTS status, final assistant text, and idle state
- publication safety: no tracked cert/model weights; token grep found only documented command examples and roadmap text, not real secrets

One warning appeared during the unit run:

- PyTorch warned that the installed NVIDIA driver is too old for CUDA initialization. Tests still passed. This is local environment noise, not a Qantara regression.

Prior validation:

Passed on 2026-04-26:

```bash
ruff check .
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m compileall -q adapters gateway providers scripts tests cli.py config.py discovery
git diff --check
docker compose config -q
QANTARA_AUTH_TOKEN=aaaaaaaaaaaaaaaaaaaaaaaa QANTARA_DOCKER_BIND=0.0.0.0 docker compose config
QANTARA_AUTH_TOKEN=<generated> QANTARA_DOCKER_BIND=0.0.0.0 docker compose up --build -d
QANTARA_AUTH_TOKEN=<generated> QANTARA_DOCKER_BIND=0.0.0.0 QANTARA_PORT=9876 docker compose up -d qantara-gateway
chromium --headless --disable-gpu --no-sandbox --user-data-dir=/tmp/qantara-chrome-smoke --dump-dom http://192.168.68.69:9876/setup/index.html
```

Results:

- `ruff`: passed
- unit tests: 161 passed
- compileall: passed
- whitespace check: passed
- Docker Compose config: passed
- Compose auth/LAN interpolation verified with a fake 24-character token
- Fresh Docker image rebuild: passed
- Docker stack health: `qantara-ollama`, `qantara-backend`, and `qantara-gateway` healthy
- LAN publish: passed on `http://192.168.68.69:9876` because host port `8765` was already occupied by a separate local Python process
- LAN auth smoke: passed; unauthenticated `/api/backends` returned `401`, `/api/auth/login` set the browser session cookie, and authenticated `/api/backends` returned backend options
- LAN WebSocket/TTS smoke: passed through `ws://192.168.68.69:9876/ws`; a real backend turn returned Kokoro TTS status and final assistant text
- Headless Chromium page smoke: passed; the LAN setup page loaded and rendered the `QANTARA_AUTH_TOKEN` auth panel
- GitHub push: passed, `public-main -> main`
- GitHub CI: passed for commit `6d2e028`

One warning appeared during the unit run:

- PyTorch warned that the installed NVIDIA driver is too old for CUDA initialization. Tests still passed. This is local environment noise, not a Qantara regression.

## Current Risk Register

Recent checkpoint on 2026-04-28:

- `v0.2.7` hardening release was tagged, pushed, and published.
- CI cleanup moved GitHub Actions to `actions/checkout@v6` and `actions/setup-python@v6`; GitHub Actions passed.
- MCP `0.2.8` client slice started:
  - `adapters/mcp_client.py` implements an agent-style MCP chat-tool adapter over stdio and streamable HTTP.
  - `QANTARA_MCP_TRANSPORT`, `QANTARA_MCP_COMMAND`, `QANTARA_MCP_URL`, and `QANTARA_MCP_CHAT_TOOL` configure the adapter.
  - Adapter progress notifications forward as `assistant_activity` events and final text flows into the normal TTS path.
  - Setup now includes an "Any MCP server" tile with a protected `tools/list` probe. Browser-driven stdio commands are intentionally not accepted; set `QANTARA_MCP_COMMAND` in the gateway environment.
  - Reference configs live in `docs/examples/mcp/`.
- MCP server/control-plane slice landed:
  - `/api/control/voice/status`, `/api/control/voice/session_start`, `/api/control/voice/speak`, `/api/control/voice/transcript`, `/api/control/voice/interrupt`, `/api/control/voice/set_voice`, and `/api/control/voice/set_translation_mode` target active browser sessions.
  - `mcp_server.py` exposes `voice_get_status`, `voice_session_start`, `voice_speak`, `voice_get_transcript`, `voice_interrupt`, `voice_set_voice`, and `voice_set_translation_mode` over stdio or streamable HTTP.
  - MCP resources expose voices, languages, avatars, active sessions, per-session status/transcript, and mesh peers.
  - The browser client now renders non-spoken `assistant_activity` events in the debug view and voice-mode overlay.
  - Tests validate no-active-browser handling, auth, browser speech queueing, and a real MCP stdio client calling `voice_speak` through the gateway.
  - A separate-process streamable HTTP smoke on 2026-04-29 validated MCP tools/list, `voice_get_status`, and `voice_speak` against an authenticated gateway with an active WebSocket voice session. The browser-side WebSocket received `assistant_text_final` from `source: control`.

Blockers before tagging a future MCP public release:

Reminder for the user: they plan to test the real desktop MCP client and physical browser voice session later. Bring this up before tagging or publishing the next MCP release.

1. Validate against a real desktop MCP client, such as Claude Desktop or Home Assistant MCP, and one physical browser voice session.
2. Decide whether the raw `docs/audits/` report should stay local, be sanitized, or be removed before any future public commit.
3. Optional: run a physical microphone/browser test on another device over HTTPS. The automated auth/WebSocket/TTS path and setup-page load already passed.

Non-blocking but important:

- Mesh and Wyoming are still plaintext trusted-LAN features. A future release should add a pre-shared key or HMAC handshake if they become more than trusted-home-LAN features.
- The setup URL safety hardening rejects dotted public-looking hostnames unless they end in `.local`, `.lan`, or `.home.arpa`; users with unusual private DNS names may need to use an IP address or supported local suffix.
- Docker image size is still large because Python ML speech dependencies are included.
- PyPI packaging is still not ready; Docker/native execution remain the supported install paths.
- Avatar motion is amplitude-driven. Phoneme lipsync remains future work.

## Recommended Next Steps

1. Validate the MCP server with a real desktop/client integration and one physical browser voice session.
2. Validate the client adapter against a real MCP target such as `claude mcp serve` or a Home Assistant MCP endpoint.
3. Keep the raw `docs/audits/` report local-only unless a sanitized version is deliberately prepared later.

## Current Readiness

Status: hardening release is published and the MCP client plus server/control-plane slices are locally validated. Fresh local validation on 2026-04-29 passed: `ruff check .`, `make test` (173 tests), `compileall`, `git diff --check`, `docker compose config -q`, stdio MCP client-to-server tool call, streamable HTTP MCP tools/list smoke, and a separate-process streamable HTTP MCP `voice_speak` smoke into an active browser WebSocket session. On 2026-04-30, focused MCP server tests passed for the expanded tools/resources, transcript reads, and translation-mode control.

Score: 97 / 100.

## 2026-05-11 Ship Checkpoint

Local lifecycle cleanup commit `f15dc73 Fix Qantara lifecycle cleanup regressions` is ready to publish from `public-main` to `origin/main`. It covers:

- OpenAI-compatible adapter per-turn cleanup on early failure and completion paths.
- Active browser session snapshot pruning by `client_session_id`.
- `/api/configure` model unload after the replacement backend binding is accepted.
- Lazy mesh/Wyoming imports for default mesh-disabled runtime paths on Windows-safe environments.

Windows-safe focused verification previously passed for `tests.test_adapter_translation_directive`, `tests.test_backend_switch`, and `tests.test_gateway_http`. Full Docker, Linux virtualenv, Ollama/OpenClaw, mesh/Wyoming, browser microphone, HTTPS/WSS, and physical MCP-client checks still require LinuxHost/runtime verification.
