# Configuration

Qantara uses environment variables, an optional two-level YAML file, source-checkout CLI flags, and a runtime setup page. These are related but not interchangeable.

## Safe defaults

Native and Docker deployments bind the browser gateway to loopback by default:

```text
127.0.0.1:8765
```

Expose Qantara to another device only with a trusted-LAN plan, HTTPS/WSS, certificate trust, and a strong auth token. Do not publish the gateway directly to the internet.

## Startup precedence

For values handled by `cli.py`, the implemented precedence is:

```text
environment variables > explicit CLI flags > selected YAML file > built-in defaults
```

An environment variable can therefore override a flag. See [CLI launcher](CLI.md) for the exact mapping.

The YAML file is selected in this order:

1. `--config PATH`
2. `QANTARA_CONFIG`
3. repository-root `qantara.yml`
4. no file

The setup page and `/api/configure` change the active backend binding in the running process. They do not rewrite the startup environment, CLI arguments, or YAML file.

## Example files

- `.env.example` contains safe environment placeholders. Python does not load `.env` automatically; use a shell/process manager that does.
- `qantara.example.yml` contains the supported YAML subset.
- `ops/session-backend.env.example` contains a custom session-backend example.

Never commit real `.env` files, tokens, TLS private keys, downloaded model weights, or machine-specific paths.

## YAML schema

Qantara intentionally uses a minimal two-level scalar parser rather than a general YAML dependency:

```yaml
backend:
  type: openai_compatible
  url: http://127.0.0.1:11434
  model: qwen3.5:2b
  agent: main

voice:
  stt: faster_whisper
  tts: piper

server:
  host: 127.0.0.1
  port: 8765
```

Unknown sections/keys, top-level scalar values, and deeper nesting are ignored. Environment variables remain the complete deployment surface.

## Core gateway and security

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_SPIKE_HOST` | `127.0.0.1` | Native gateway bind host |
| `QANTARA_SPIKE_PORT` | `8765` | Native gateway port |
| `QANTARA_DOCKER_BIND` | `127.0.0.1` | Host interface used by Docker port publishing |
| `QANTARA_PORT` | `8765` | Host port used by Docker publishing |
| `QANTARA_TLS_CERT` | unset | TLS certificate path |
| `QANTARA_TLS_KEY` | unset | TLS private-key path |
| `QANTARA_AUTH_TOKEN` | unset | Optional 24+ character token for browser login and protected API/WebSocket routes |
| `QANTARA_ADMIN_TOKEN` | unset | Optional 24+ character bearer token for `/api/admin/runtime`; endpoint is disabled when unset |
| `QANTARA_ALLOWED_HOSTS` | unset | Comma-separated extra exact internal hostnames accepted by the Host guard |
| `QANTARA_ALLOWED_ORIGINS` | unset | Comma-separated exact full browser origins allowed to differ from request authority |
| `QANTARA_BRIDGE_LOG_OUTPUT` | unset | Set to `1` only for controlled managed-bridge diagnostics |

## High-level CLI selection

These variables participate in the source-checkout CLI's startup precedence:

| Variable | Purpose |
|---|---|
| `QANTARA_BACKEND` | High-level backend choice used by `cli.py` |
| `QANTARA_OLLAMA_MODEL` | CLI/managed Ollama model override |
| `QANTARA_OPENCLAW_AGENT_ID` | CLI/managed OpenClaw agent override |
| `QANTARA_CONFIG` | YAML file path when `--config` is absent |

Lower-level direct server runs use `QANTARA_ADAPTER` and the adapter-specific settings below.

## OpenAI-compatible adapter

Recommended for Ollama and other local `/v1/chat/completions` servers:

| Variable | Default/example | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `openai_compatible` | Select direct chat-completions adapter |
| `QANTARA_OPENAI_BASE_URL` | unset (required) | Backend base URL; do not append `/chat/completions` |
| `QANTARA_OPENAI_MODEL` | unset (required for turns) | Model id; the setup UI may help select one, but the adapter does not invent a default |
| `QANTARA_OPENAI_API_KEY` | `not-needed` | Bearer value sent to compatible servers; set a real key only when the server requires one |
| `QANTARA_OPENAI_SYSTEM_PROMPT` | short voice-assistant prompt | System instruction retained at the start of each session history |
| `QANTARA_OPENAI_TIMEOUT_CONNECT` | `5` | Connect/probe timeout in seconds |
| `QANTARA_OPENAI_TIMEOUT_FIRST_TOKEN` | `30` | First-token timeout in seconds |
| `QANTARA_OPENAI_REASONING_EFFORT` | unset | Optional compatible-server control; `none` can reduce voice latency where supported |
| `QANTARA_OPENAI_MAX_SESSIONS` | `64` | LRU-bounded adapter session histories |

## Session HTTP adapter

For a custom backend implementing Qantara's session contract:

| Variable | Default/example | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `session_gateway_http` | Select generic session HTTP adapter |
| `QANTARA_BACKEND_BASE_URL` | unset (required) | Backend URL; managed bridges normally use loopback port `19120` |
| `QANTARA_BACKEND_TOKEN` | unset | Optional bearer token |
| `QANTARA_BACKEND_TIMEOUT` | `30` | Request and event-stream timeout in seconds |

See [`adapters/CONTRACT.md`](../adapters/CONTRACT.md).

## Ollama bridge

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Native Ollama API base URL |
| `QANTARA_OLLAMA_MODEL` | `qwen3.5:2b` | Native bridge model id |
| `QANTARA_OLLAMA_THINK` | `false` | Include reasoning internally; reasoning is never spoken and adds latency |
| `QANTARA_REAL_BACKEND_HOST` | `127.0.0.1` | Manual bridge bind host |
| `QANTARA_REAL_BACKEND_PORT` | `19120` | Manual bridge port |

`python cli.py --backend ollama` manages the loopback bridge automatically.

## OpenClaw bridge

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_OPENCLAW_BIN` | `openclaw` | CLI binary |
| `QANTARA_OPENCLAW_AGENT_ID` | `main` | Agent id |
| `QANTARA_OPENCLAW_TIMEOUT` | `300` | Per-turn timeout in seconds |
| `QANTARA_OPENCLAW_AGENTS_TIMEOUT` | `60` | Agent-list discovery timeout in seconds |
| `QANTARA_OPENCLAW_HEALTH_MODE` | `shallow` | Keep health lightweight; `deep` explicitly runs a diagnostic agent turn |
| `QANTARA_OPENCLAW_HEALTH_TIMEOUT` | `25` | Deep-health timeout in seconds |

OpenClaw is an advanced optional path and is hidden from setup when the host integration is unavailable.

## MCP client and server

Client adapter:

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `mcp_client` | Select MCP client adapter |
| `QANTARA_MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `QANTARA_MCP_COMMAND` | unset | Stdio server command |
| `QANTARA_MCP_URL` | unset | Private/loopback streamable HTTP URL |
| `QANTARA_MCP_CHAT_TOOL` | `chat` | Tool called for each finalized turn |
| `QANTARA_MCP_CHAT_ARG` | auto-detected | Explicit transcript argument name when schema inference is unsuitable |
| `QANTARA_MCP_TIMEOUT` | `120` | Tool-call timeout in seconds |
| `QANTARA_MCP_MAX_SESSIONS` | `64` | LRU-bounded MCP adapter sessions |

Voice-control MCP server:

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_GATEWAY_URL` | `http://127.0.0.1:8765` | Gateway control-plane URL |
| `QANTARA_GATEWAY_TOKEN` | unset | Gateway auth token for MCP callers |
| `QANTARA_MCP_SERVER_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `QANTARA_MCP_SERVER_HOST` | `127.0.0.1` | HTTP bind host |
| `QANTARA_MCP_SERVER_PORT` | `8766` | HTTP port |
| `QANTARA_MCP_SERVER_PATH` | `/mcp` | Streamable HTTP path |
| `QANTARA_MCP_SERVER_TIMEOUT` | `30` | Gateway-control request timeout in seconds |
| `QANTARA_MCP_SERVER_LOG_LEVEL` | `ERROR` | MCP server log level |
| `QANTARA_MCP_SERVER_ALLOW_INSECURE` | unset | Explicitly permits non-loopback MCP HTTP binding; dangerous because this control plane has no inbound auth |

See [MCP](MCP.md) for security and tool/resource behavior.

## Speech providers

The native provider factory defaults to faster-whisper STT and Piper TTS. Docker Compose explicitly overrides TTS to Kokoro (`QANTARA_TTS_PROVIDER=kokoro`) because the Docker speech stack includes Kokoro rather than Piper.

| Variable | Native default | Purpose |
|---|---|---|
| `QANTARA_STT_PROVIDER` | `faster_whisper` | STT selector |
| `QANTARA_WHISPER_MODEL` | `small` | faster-whisper model |
| `QANTARA_WHISPER_DEVICE` | `cpu` | faster-whisper device |
| `QANTARA_WHISPER_COMPUTE` | `int8` | faster-whisper compute type |
| `QANTARA_WHISPER_PARTIAL_WINDOW_SEC` | `2.0` | Audio window used for partial transcription |
| `QANTARA_TTS_PROVIDER` | `piper` | TTS selector: `piper`, `kokoro`, or `chatterbox` |
| `QANTARA_VOICE_REGISTRY` | `identity/voice-registry/voices.json` | Voice registry path |
| `QANTARA_PIPER_MODEL` | first registry/default model | Fallback Piper model path |
| `QANTARA_PIPER_VOICE` | first available | Preferred Piper voice id |
| `QANTARA_PIPER_TIMEOUT` | `60` | One Piper synthesis timeout in seconds |
| `QANTARA_KOKORO_VOICE` | `af_heart` | Kokoro voice id |
| `QANTARA_KOKORO_REPO_ID` | `hexgrad/Kokoro-82M` | Kokoro model repository |
| `QANTARA_KOKORO_DEVICE` | `cpu` | Kokoro device |
| `QANTARA_DEFAULT_SPEECH_RATE` | `1.2` | New-session speech-rate multiplier |

Piper's Python runtime/module and voice files are operator-supplied. Download repository-listed voices with `scripts/fetch_piper_voices.sh`. Model caches and voice assets are not committed.

## Mesh and Wyoming

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_MESH_ROLE` | `disabled` | `full`, `mic-only`, `speaker-only`, or `disabled` |
| `QANTARA_MESH_HOST` | `127.0.0.1` | Mesh TCP bind host |
| `QANTARA_MESH_PORT` | `8901` | Mesh TCP port |
| `QANTARA_MESH_NODE_ID` | generated | Stable node id |
| `QANTARA_MESH_SERVICE_TYPE` | `_qantara._tcp.local.` | mDNS service type |
| `QANTARA_MESH_TOKEN` | unset | Shared HMAC secret; use the same value on every node |
| `QANTARA_WYOMING_ENABLED` | `false` | Enable Home Assistant Wyoming satellite mode |
| `QANTARA_WYOMING_HOST` | `127.0.0.1` | Wyoming bind host |
| `QANTARA_WYOMING_PORT` | `10700` | Wyoming port |
| `QANTARA_WYOMING_NODE_NAME` | `qantara` | Advertised satellite name |
| `QANTARA_WYOMING_AREA` | unset | Optional Home Assistant area |

Changing a bind host to `0.0.0.0` is an explicit trusted-LAN exposure decision. See [Mesh](MESH.md) and [Home Assistant](HOMEASSISTANT.md).

## Capacity, continuity, and timeouts

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_MAX_WEBSOCKET_CONNECTIONS` | `64` | Simultaneous WebSocket ceiling |
| `QANTARA_SESSION_STORE_LIMIT` | `256` | Resumable snapshot ceiling |
| `QANTARA_SESSION_STORE_TTL_MS` | `1800000` | Snapshot TTL (30 minutes) |
| `QANTARA_SESSION_TIMELINE_LIMIT` | `200` | Timeline items retained per active session |
| `QANTARA_SESSION_TRANSCRIPT_LIMIT` | `80` | Transcript items retained per active session |
| `QANTARA_TURN_CANCEL_GRACE_MS` | `750` | Adapter cancellation grace before task escalation |
| `QANTARA_VOICE_API_TURN_TIMEOUT` | `120` | Converse SSE turn deadline in seconds |

Control-plane JSON bodies are capped at 1 MiB. WebSocket messages are capped at 256 KiB, with 64 KiB control-message and PCM-frame limits. Voice API text is capped at 16 KiB, one-shot transcription uploads at 32 MiB, generated/backend stream content at 1 MiB, and Piper raw output at 64 MiB. These fixed limits protect the process and reflect uncompressed PCM sizes rather than permission to retain content.

## URL, Host, and Origin safety

The setup page, `/api/configure`, and backend probes reject public URLs and URLs with embedded credentials. Accepted targets are loopback, private LAN IPs, single-label local names, and names ending in `.local`, `.lan`, or `.home.arpa`. Validated hostnames are pinned to a private address for the request while preserving the original Host authority and HTTPS server name. Probes do not follow redirects or inherit proxy variables.

The inbound Host guard uses the same local/LAN policy. `QANTARA_ALLOWED_HOSTS` adds exact internal names; `QANTARA_ALLOWED_ORIGINS` adds exact full origins when a deliberate reverse-proxy topology requires it.

## Privacy

Default event logs redact transcripts, assistant text, tool parameters, and credentials. `QANTARA_BRIDGE_LOG_OUTPUT=1` is opt-in because backend-controlled stdout/stderr can contain sensitive content. Review diagnostic output before sharing it.
