# Configuration

Qantara is configured with environment variables, setup-page choices, and optional YAML config. Environment variables are the clearest path for deployment.

## Safe Defaults

Native runs bind to loopback by default:

```text
127.0.0.1:8765
```

Docker publishes to loopback by default:

```text
127.0.0.1:8765
```

Expose Qantara to a LAN only when you understand the trust boundary and can use HTTPS for browser microphone access.

## Example Files

- `.env.example` shows safe environment variable placeholders.
- `qantara.example.yml` shows a sample YAML config.
- `ops/session-backend.env.example` shows a session-backend adapter sample.

Do not commit real `.env` files, tokens, TLS private keys, or downloaded model weights.

## Core Gateway Variables

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_SPIKE_HOST` | `127.0.0.1` | Gateway bind host |
| `QANTARA_SPIKE_PORT` | `8765` | Gateway port |
| `QANTARA_DOCKER_BIND` | `127.0.0.1` | Host interface for Docker port publishing |
| `QANTARA_PORT` | `8765` | Host port for Docker port publishing |
| `QANTARA_TLS_CERT` | unset | Path to local TLS certificate |
| `QANTARA_TLS_KEY` | unset | Path to local TLS private key |
| `QANTARA_AUTH_TOKEN` | unset | Optional 24+ character token for browser login and protected API/WebSocket endpoints |
| `QANTARA_ADMIN_TOKEN` | unset | Optional 24+ character bearer token for `/api/admin/runtime`; endpoint is disabled when unset |
| `QANTARA_ALLOWED_HOSTS` | unset | Comma-separated additional internal hostnames accepted by the Host guard |
| `QANTARA_ALLOWED_ORIGINS` | unset | Comma-separated exact browser origins allowed to differ from the request authority |
| `QANTARA_BRIDGE_LOG_OUTPUT` | unset | Set to `1` only to opt into managed bridge stdout/stderr diagnostics |

## Backend Variables

Recommended OpenAI-compatible path:

| Variable | Example | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `openai_compatible` | Selects direct chat-completions adapter |
| `QANTARA_OPENAI_BASE_URL` | `http://127.0.0.1:11434` | Base URL for the local backend |
| `QANTARA_OPENAI_MODEL` | auto-detected | Model id; set explicitly when the server exposes more than one |
| `QANTARA_OPENAI_API_KEY` | `not-needed` | Optional bearer token for compatible servers that require one |
| `QANTARA_OPENAI_REASONING_EFFORT` | unset | Optional compatible-server control; use `none` with current Ollama when low voice latency is preferred |
| `QANTARA_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL used by the setup probe and Ollama bridge |
| `QANTARA_OLLAMA_MODEL` | `qwen3.5:2b` | Ollama bridge model id |
| `QANTARA_OLLAMA_THINK` | `false` | Include Ollama reasoning; reasoning is never spoken, and enabling it adds latency |

Session HTTP bridge path:

| Variable | Example | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `session_gateway_http` | Selects Qantara's session contract adapter |
| `QANTARA_BACKEND_BASE_URL` | `http://127.0.0.1:19120` | Session backend URL |
| `QANTARA_BACKEND_TOKEN` | unset | Optional bearer token for custom session backends |

Advanced optional OpenClaw path:

| Variable | Example | Purpose |
|---|---|---|
| `QANTARA_OPENCLAW_BIN` | `openclaw` | CLI binary |
| `QANTARA_OPENCLAW_AGENT_ID` | `main` | Agent id to call |
| `QANTARA_OPENCLAW_TIMEOUT` | `300` | Per-turn timeout |
| `QANTARA_OPENCLAW_AGENTS_TIMEOUT` | `60` | Setup discovery timeout for listing agents; timed-out children are killed and reaped |
| `QANTARA_OPENCLAW_HEALTH_MODE` | `shallow` | Health endpoint mode. Keep `shallow` for normal use so health checks do not run agent turns; set `deep` only for explicit diagnostics. |

OpenClaw is hidden from setup unless the host gateway is healthy. It is not the default local LLM path.

## Speech Variables

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_STT_PROVIDER` | `faster_whisper` | Speech-to-text provider |
| `QANTARA_WHISPER_MODEL` | `small` | faster-whisper model |
| `QANTARA_WHISPER_DEVICE` | provider default | `cpu`, `cuda`, etc. |
| `QANTARA_WHISPER_COMPUTE` | provider default | compute type such as `int8` |
| `QANTARA_TTS_PROVIDER` | `piper` | Text-to-speech provider |
| `QANTARA_PIPER_VOICE` | first available | Piper voice id |
| `QANTARA_PIPER_TIMEOUT` | `60` | Maximum seconds for one Piper subprocess synthesis |
| `QANTARA_VOICE_REGISTRY` | `identity/voice-registry/voices.json` | Voice registry file |
| `QANTARA_KOKORO_VOICE` | provider default | Kokoro voice id |
| `QANTARA_KOKORO_REPO_ID` | `hexgrad/Kokoro-82M` | Kokoro model repository override |
| `QANTARA_KOKORO_DEVICE` | provider default | Kokoro device |
| `QANTARA_DEFAULT_SPEECH_RATE` | `1.0` | User-level speech-rate multiplier |

Piper voices are downloaded with:

```bash
scripts/fetch_piper_voices.sh
```

Downloaded Piper `.onnx` files, local model caches, and local certs are ignored by git.

## Mesh and Wyoming Variables

Mesh and Wyoming are opt-in and bind to loopback by default. Set the host to `0.0.0.0` only when you intentionally want LAN peers to reach the service.

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_MESH_ROLE` | `disabled` | `full`, `mic-only`, `speaker-only`, or `disabled` |
| `QANTARA_MESH_HOST` | `127.0.0.1` | Mesh TCP bind host |
| `QANTARA_MESH_PORT` | `8901` | Mesh TCP port |
| `QANTARA_MESH_NODE_ID` | generated | Stable node id for peer election |
| `QANTARA_MESH_SERVICE_TYPE` | `_qantara._tcp.local.` | mDNS service name |
| `QANTARA_MESH_TOKEN` | unset | Optional shared secret; signs every mesh frame (HMAC-SHA256) and drops unsigned/mismatched frames. Set the same value on every node |
| `QANTARA_WYOMING_ENABLED` | `false` | Enables Home Assistant Wyoming satellite mode |
| `QANTARA_WYOMING_HOST` | `127.0.0.1` | Wyoming TCP bind host |
| `QANTARA_WYOMING_PORT` | `10700` | Wyoming TCP port |
| `QANTARA_WYOMING_NODE_NAME` | `qantara` | Satellite name shown in Home Assistant |
| `QANTARA_WYOMING_AREA` | unset | Optional Home Assistant area |

## URL Safety

The setup page, `/api/configure`, and `/api/test-url` reject public backend URLs and URLs with embedded credentials. Use loopback, private LAN IPs, single-label local hostnames, or hostnames ending in `.local`, `.lan`, or `.home.arpa`. Validated names are pinned to a private address before use, and probes do not follow redirects or inherit proxy variables. This is intentional SSRF and DNS-rebinding protection.

The inbound Host guard uses the same local/LAN policy. Add an exact custom internal DNS hostname with `QANTARA_ALLOWED_HOSTS`; do not use it to approve a public hostname. Browser Origin checks compare both hostname and port. `QANTARA_ALLOWED_ORIGINS` is an explicit exception list and should contain complete origins such as `https://voice.example.internal`.

## Privacy and request limits

Default event logs redact free-form content and credentials. `QANTARA_BRIDGE_LOG_OUTPUT=1` can expose backend-controlled output and should be enabled only during controlled local troubleshooting.

Control-plane JSON bodies are capped at 1 MiB. WebSocket messages are capped at
256 KiB, with 64 KiB control-message and PCM-frame limits. Voice API text is
capped at 16 KiB, generated assistant text and backend stream lines at 1 MiB,
and one-shot transcription uploads at 32 MiB. Piper raw audio capture has a
64 MiB ceiling so subprocess output cannot grow without bound. The larger audio
limits reflect uncompressed PCM rather than control data.

The gateway permits 64 simultaneous WebSocket connections by default and
retains at most 256 resumable session snapshots. Override these ceilings with
`QANTARA_MAX_WEBSOCKET_CONNECTIONS` and `QANTARA_SESSION_STORE_LIMIT` when a
known deployment needs different bounds. Mock and runtime-skeleton adapters
also retain at most 64 sessions and 24 turns per session.

`QANTARA_VOICE_API_TURN_TIMEOUT` controls the converse SSE turn deadline
(default 120 seconds), and `QANTARA_PIPER_TIMEOUT` controls one Piper synthesis
(default 60 seconds).

## Configuration Precedence

When multiple sources are used, prefer this order:

1. Environment variables for deployment
2. Setup page for interactive local use
3. `qantara.yml` for local repeatability
4. Built-in defaults
