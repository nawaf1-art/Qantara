# Configuration

Qantara uses environment variables, an optional two-level YAML file, `qantara` CLI flags, and a runtime setup page. These are related but not interchangeable.

## Safe defaults

Native and Docker deployments bind the browser gateway to loopback by default:

```text
127.0.0.1:8765
```

Without `QANTARA_AUTH_TOKEN` the gateway fails closed: it serves only requests whose `Host` is `localhost`, an address in `127.0.0.0/8`, `::1`, or an exact `QANTARA_ALLOWED_HOSTS` entry. Every other request gets HTTP 421 with a JSON body containing `"code": "lan_access_requires_token"`. This applies to a reverse proxy that forwards a LAN `Host` (the Caddy setup forwards `Host: qantara.local`) and to Docker opened by its LAN IP. The Python SDK logs a warning when `VoiceGateway(host=...)` binds a non-loopback interface without a token.

Expose Qantara to another device only with a trusted-LAN plan, HTTPS/WSS, certificate trust, and a strong auth token. Do not publish the gateway directly to the internet.

## Startup precedence

For values handled by the `qantara` launcher (`python cli.py` in a source checkout), the implemented precedence is:

```text
explicit CLI flags > environment variables > selected YAML file > built-in defaults
```

A flag always wins over an exported variable, and a variable wins over `qantara.yml`. See [CLI launcher](CLI.md) for the exact mapping.

The YAML file is selected in this order:

1. `--config PATH` (startup fails if the file does not exist)
2. `QANTARA_CONFIG` (startup fails if the file does not exist)
3. `qantara.yml` in the current directory
4. `qantara.yml` in the source-checkout root
5. no file

Configuration errors stop the launcher with exit code 2 and a message that names the source, for example `QANTARA_SPIKE_PORT must be an integer, got 'abc'`. Unknown YAML sections or keys produce a warning and are ignored.

The setup page and `/api/configure` change the active backend binding in the running process. They do not rewrite the startup environment, CLI arguments, or YAML file. The setup page's TTS engine choice (including **Automatic**) takes effect immediately without a restart and is likewise not persisted.

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
  tts: auto

server:
  host: 127.0.0.1
  port: 8765
```

Unknown sections/keys produce a warning and are ignored; top-level scalar values and deeper nesting are not supported. Values may be quoted with `"..."` or `'...'`; `#` starts a comment only at the start of a value or after whitespace. Environment variables remain the complete deployment surface.

## Core gateway and security

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_SPIKE_HOST` | `127.0.0.1` | Native gateway bind host |
| `QANTARA_SPIKE_PORT` | `8765` | Native gateway port |
| `QANTARA_DOCKER_BIND` | `127.0.0.1` | Host interface used by Docker port publishing |
| `QANTARA_PORT` | `8765` | Host port used by Docker publishing |
| `QANTARA_TLS_CERT` | unset | TLS certificate path |
| `QANTARA_TLS_KEY` | unset | TLS private-key path |
| `QANTARA_AUTH_TOKEN` | unset | 24+ character token for browser login and protected API/WebSocket routes; required for any non-loopback access. Whitespace and control characters are rejected at startup; non-ASCII tokens work (compared as UTF-8 bytes; API clients must send the header UTF-8 encoded) |
| `QANTARA_AUTH_SESSION_TTL_SECONDS` | `43200` (12 h) | Lifetime of one browser login session; must be a positive integer |
| `QANTARA_ADMIN_TOKEN` | unset | Optional 24+ character bearer token for `/api/admin/runtime`; endpoint is disabled when unset |
| `QANTARA_ALLOWED_HOSTS` | unset | Comma-separated exact hostnames accepted by the Host guard; the only way to serve a non-loopback `Host` without a token |
| `QANTARA_ALLOWED_ORIGINS` | unset | Comma-separated exact full browser origins allowed to differ from request authority, including cross-site `/api/*` requests |
| `QANTARA_ALLOW_CGNAT` | unset | Set to `1` to treat CGNAT/Tailscale `100.64.0.0/10` as a private backend target |
| `QANTARA_BRIDGE_LOG_OUTPUT` | unset | Set to `1` only for controlled managed-bridge diagnostics |

Browser logins are server-side sessions: each login gets its own random session id (at most 256 are kept; the oldest is evicted), logout revokes it, and all sessions are lost when the gateway restarts. After 10 distinct wrong credentials from one client within a minute, further attempts get HTTP 429 with `Retry-After`. Behind a loopback reverse proxy the client is identified by the last `X-Forwarded-For` entry.

When a token is set, `/api/tts` and `/api/languages` require authentication like the other protected routes. `/api/status` reports only the MCP program basename and an `mcp_command_configured` flag, never the full command line.

## High-level CLI selection

These variables participate in the launcher's startup precedence (a matching flag overrides them):

| Variable | Purpose |
|---|---|
| `QANTARA_BACKEND` | High-level backend choice (`--backend`) |
| `QANTARA_OLLAMA_MODEL` | Ollama model (`--model`) |
| `QANTARA_OPENCLAW_AGENT_ID` | OpenClaw agent (`--agent`) |
| `QANTARA_SPIKE_HOST` / `QANTARA_SPIKE_PORT` | Bind host/port (`--host` / `--port`) |
| `QANTARA_CONFIG` | YAML file path when `--config` is absent |

Lower-level direct server runs use `QANTARA_ADAPTER` and the adapter-specific settings below.

## OpenAI-compatible adapter

Recommended for Ollama and other local `/v1/chat/completions` servers:

| Variable | Default/example | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `openai_compatible` | Select direct chat-completions adapter |
| `QANTARA_OPENAI_BASE_URL` | unset (required) | Backend base URL; do not append `/chat/completions` |
| `QANTARA_OPENAI_MODEL` | unset (required for turns) | Model id; the setup UI may help select one, but the adapter does not invent a default. Health reports `degraded` when the server does not serve this model |
| `QANTARA_OPENAI_API_KEY` | `not-needed` | Bearer value sent to compatible servers; set a real key only when the server requires one |
| `QANTARA_OPENAI_SYSTEM_PROMPT` | short voice-assistant prompt | System instruction; per-turn voice context is merged into the same single system message |
| `QANTARA_OPENAI_TIMEOUT_CONNECT` | `5` | Connect/probe timeout in seconds |
| `QANTARA_OPENAI_TIMEOUT_FIRST_TOKEN` | `30` | Seconds to wait for the first token and for each later read of the stream |
| `QANTARA_OPENAI_REASONING_EFFORT` | unset | Optional compatible-server control; `none` can reduce voice latency where supported |
| `QANTARA_OPENAI_REASONING_START` | `auto` | Inline `<think>` handling: `auto`, `inside` (the stream starts inside a reasoning block), or `outside`. Reasoning is never spoken |
| `QANTARA_OPENAI_MAX_TOKENS` | `512` | `max_tokens` sent per reply; `0` omits it |
| `QANTARA_OPENAI_HISTORY_CHAR_BUDGET` | `8000` | Character budget for retained history, trimmed in whole user/assistant exchanges. A context-length rejection drops the oldest exchange and retries once |
| `QANTARA_OPENAI_MAX_SESSIONS` | `64` | LRU-bounded adapter session histories |

## Session HTTP adapter

For a custom backend implementing the [session gateway HTTP protocol](../protocols/session-gateway-http.md):

| Variable | Default/example | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `session_gateway_http` | Select generic session HTTP adapter |
| `QANTARA_BACKEND_BASE_URL` | unset (required) | Backend URL; managed bridges normally use loopback port `19120` |
| `QANTARA_BACKEND_TOKEN` | unset | Optional bearer token |
| `QANTARA_BACKEND_TIMEOUT` | `30` | Total seconds for each short JSON request (session, turn, cancel, health). It no longer bounds the event stream |
| `QANTARA_BACKEND_CONNECT_TIMEOUT` | `10` | Seconds to connect for the event stream |
| `QANTARA_BACKEND_IDLE_TIMEOUT` | `90` | Seconds the event stream may stay silent before the turn fails (the backend is then asked to cancel) |

See [`adapters/CONTRACT.md`](../adapters/CONTRACT.md).

## Managed bridges (Ollama and OpenClaw)

Shared by the bundled session backends:

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_BACKEND_KEEPALIVE_SECONDS` | `10` | Interval of the `thinking` keep-alive activity a bridge sends while waiting on its model or agent, so the gateway idle timeout does not fire |
| `QANTARA_BACKEND_MAX_SESSIONS` | `64` | LRU-bounded bridge sessions |
| `QANTARA_REAL_BACKEND_HOST` | `127.0.0.1` | Manual bridge bind host |
| `QANTARA_REAL_BACKEND_PORT` | `19120` | Manual bridge port |

Ollama bridge:

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Native Ollama API base URL |
| `QANTARA_OLLAMA_MODEL` | `qwen3.5:2b` | Native bridge model id; health reports `degraded` when it is not pulled |
| `QANTARA_OLLAMA_THINK` | `false` | Include reasoning internally; reasoning is never spoken and adds latency |
| `QANTARA_OLLAMA_TIMEOUT` | `120` | Seconds Ollama may stay silent (an idle bound, not a total turn limit) |
| `QANTARA_OLLAMA_KEEP_ALIVE` | `15m` | Ollama model keep-alive |
| `QANTARA_OLLAMA_SYSTEM_PROMPT` | unset | Replaces the bridge's built-in voice prompt |
| `QANTARA_MAX_HISTORY_TURNS` | `6` | Exchanges of history the bridge sends to Ollama |
| `QANTARA_ASSISTANT_NAME` / `QANTARA_ASSISTANT_ROLE` / `QANTARA_BUSINESS_NAME` / `QANTARA_VOICE_STYLE` | `Qantara` / `a voice assistant` / unset / `calm, direct, and helpful` | Inputs to the built-in prompt |

`qantara --backend ollama` manages the loopback bridge automatically.

OpenClaw bridge:

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_OPENCLAW_BIN` | `openclaw` | CLI binary |
| `QANTARA_OPENCLAW_AGENT_ID` | `main` | Agent id |
| `QANTARA_OPENCLAW_TIMEOUT` | `300` | Per-turn timeout in seconds |
| `QANTARA_OPENCLAW_TIMEOUT_BUFFER` | `30` | Extra seconds before the CLI subprocess is killed |
| `QANTARA_OPENCLAW_CANCEL_GRACE` | `2` | Seconds a cancelled turn's CLI process gets before it is force-killed |
| `QANTARA_OPENCLAW_THINKING` | unset | Optional OpenClaw thinking level |
| `QANTARA_OPENCLAW_AGENTS_TIMEOUT` | `60` | Agent-list discovery timeout in seconds |
| `QANTARA_OPENCLAW_HEALTH_MODE` | `shallow` | Keep health lightweight; `deep` explicitly runs a diagnostic agent turn |
| `QANTARA_OPENCLAW_HEALTH_TIMEOUT` | `25` | Deep-health timeout in seconds |

OpenClaw is an advanced optional path and is hidden from setup when the host integration is unavailable. A turn cancelled while it is still queued never starts.

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
| `QANTARA_MCP_SERVER_HOST` | `127.0.0.1` | HTTP bind host; an empty value also means `127.0.0.1` |
| `QANTARA_MCP_SERVER_PORT` | `8766` | HTTP port |
| `QANTARA_MCP_SERVER_PATH` | `/mcp` | Streamable HTTP path |
| `QANTARA_MCP_SERVER_TIMEOUT` | `30` | Gateway-control request timeout in seconds |
| `QANTARA_MCP_SERVER_LOG_LEVEL` | `ERROR` | MCP server log level |
| `QANTARA_MCP_SERVER_ALLOW_INSECURE` | unset | Explicitly permits a non-loopback MCP HTTP bind (including `0.0.0.0` and `::`); dangerous because this control plane has no inbound auth |
| `QANTARA_CONTROL_MAX_SPEAK_CHARS` | `4000` | Text limit for `/api/control/voice/speak` |

See [MCP](MCP.md) for security and tool/resource behavior.

## Speech providers

The native provider factory defaults to faster-whisper STT and `QANTARA_TTS_PROVIDER=auto`. Docker Compose explicitly sets `QANTARA_TTS_PROVIDER=kokoro` because the Docker speech stack includes Kokoro but not Piper.

`auto` chooses at startup: when Kokoro is importable and a Piper voice is usable it routes by language (Kokoro for English, Spanish, and French; Piper for Arabic and anything Kokoro lacks); otherwise it uses Kokoro alone; otherwise Piper. `routed` forces language routing. Whatever the selection, text that no installed voice can speak raises `no_voice_for_language`, which the browser shows as a plain message, instead of being read with a voice for another script.

| Variable | Native default | Purpose |
|---|---|---|
| `QANTARA_STT_PROVIDER` | `faster_whisper` | STT selector |
| `QANTARA_WHISPER_MODEL` | `small` | faster-whisper model |
| `QANTARA_WHISPER_DEVICE` | `cpu` | faster-whisper device |
| `QANTARA_WHISPER_COMPUTE` | `int8` | faster-whisper compute type |
| `QANTARA_WHISPER_BEAM_SIZE` | `1` on CPU, `5` on CUDA | Decoding beam size |
| `QANTARA_STT_LANGUAGES` | unset (all) | Comma-separated languages detection may choose, e.g. `en,ar`; `fa`, `ur`, and `ps` detections fold into `ar` |
| `QANTARA_STT_STREAMING` | `auto` | Partial transcripts: `on`, `off`, or `auto` (on for CUDA/MPS devices) |
| `QANTARA_WHISPER_PARTIAL_WINDOW_SEC` | `2.0` | Audio window used for partial transcription |
| `QANTARA_MAX_UTTERANCE_MS` | `30000` | Maximum audio captured for one utterance (400 ms of pre-roll is kept before speech onset) |
| `QANTARA_TTS_PROVIDER` | `auto` | TTS selector: `auto`, `routed`, `piper`, `kokoro`, or `chatterbox` |
| `QANTARA_TTS_WARMUP` | unset | Set to `1` to load TTS at startup instead of on the first reply |
| `QANTARA_VOICE_REGISTRY` | `identity/voice-registry/voices.json` | Voice registry path |
| `QANTARA_PIPER_MODEL` | first registry/default model | Explicit Piper model path; honored when set |
| `QANTARA_PIPER_VOICE` | first available | Preferred Piper voice id |
| `QANTARA_PIPER_IN_PROCESS` | `1` | Run Piper in-process when `piper-tts` is importable; `0` uses a `python -m piper` subprocess |
| `QANTARA_PIPER_TIMEOUT` | `60` | One Piper synthesis timeout in seconds |
| `QANTARA_KOKORO_VOICE` | `af_heart` | Kokoro voice id |
| `QANTARA_KOKORO_REPO_ID` | `hexgrad/Kokoro-82M` | Kokoro model repository |
| `QANTARA_KOKORO_DEVICE` | `cpu` | Kokoro device |
| `QANTARA_OFFLINE` | unset | Set to `1` (or `HF_HUB_OFFLINE=1`) so Kokoro fails clearly instead of downloading the missing spaCy model |
| `QANTARA_CHATTERBOX_DEVICE` | `cpu` | Chatterbox device |
| `QANTARA_DEFAULT_SPEECH_RATE` | `1.2` | New-session speech-rate multiplier; the browser speed slider overrides it only after it is moved |

In directional and live translation modes the declared source language is passed to STT instead of being auto-detected.

Piper's `piper-tts` package and voice files are operator-supplied. `scripts/fetch_piper_voices.sh` downloads the repository-listed English, Spanish, French, and Arabic voices from a pinned revision and verifies each file's SHA-256. Kokoro's English pipeline needs `python -m spacy download en_core_web_sm` on native installs. Model caches and voice assets are not committed.

## Mesh

| Variable | Default | Purpose |
|---|---|---|
| `QANTARA_MESH_ROLE` | `disabled` | `full`, `mic-only`, or `speaker-only`; `disabled`, `off`, `false`, `0`, `no`, `none`, or empty disable the mesh; any other value aborts startup |
| `QANTARA_MESH_HOST` | `127.0.0.1` | Mesh TCP bind host; a loopback bind starts no mDNS discovery |
| `QANTARA_MESH_PORT` | `8901` | Mesh TCP port |
| `QANTARA_MESH_NODE_ID` | generated | Stable node id matching `^[A-Za-z0-9._-]{1,64}$` |
| `QANTARA_MESH_SERVICE_TYPE` | `_qantara._tcp.local.` | mDNS service type |
| `QANTARA_MESH_TOKEN` | unset | Shared HMAC secret, 24+ characters, same value on every node; required for a non-loopback bind |
| `QANTARA_MESH_ALLOW_INSECURE` | unset | Set to `1` to start a non-loopback mesh without a token (unauthenticated frames) |

Changing a bind host to `0.0.0.0` is an explicit trusted-LAN exposure decision. See [Mesh](MESH.md).

The Home Assistant Wyoming bridge and its `QANTARA_WYOMING_*` variables were removed in `0.4.0`; a leftover `QANTARA_WYOMING_ENABLED` logs a warning and is otherwise ignored. See [Home Assistant](HOMEASSISTANT.md).

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
| `QANTARA_VOICE_API_MAX_SPEAK_CHARS` | `4000` | `/api/v1/speak` text limit (longer text gets 413) |
| `QANTARA_TRANSCRIBE_MAX_SECONDS` | `120` | Longest clip `/api/v1/transcribe` accepts (longer clips get 400) |
| `QANTARA_VOICE_API_CONCURRENCY` | `2` | Concurrent speak/transcribe jobs; further requests wait |
| `QANTARA_MOCK_MAX_SESSIONS` / `QANTARA_RUNTIME_SKELETON_MAX_SESSIONS` | `64` | Session bounds of the development adapters |

Control-plane JSON bodies are capped at 1 MiB. WebSocket messages are capped at 256 KiB, with 64 KiB control-message and PCM-frame limits. Converse text is capped at 16 KiB, one-shot transcription uploads at 32 MiB (sample rates 8000–48000 Hz), generated/backend stream content at 1 MiB, and Piper raw output at 64 MiB. These fixed limits protect the process and reflect uncompressed PCM sizes rather than permission to retain content.

## URL, Host, and Origin safety

The setup page, `/api/configure`, and backend probes reject public URLs and URLs with embedded credentials. Accepted targets are an explicit allowlist: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `::1`, IPv6 ULA `fc00::/7`, single-label local names, and names ending in `.local`, `.lan`, or `.home.arpa`. Link-local addresses (including the `169.254.169.254` cloud metadata address, `fe80::/10`, and `fd00:ec2::254`), 6to4 `2002::/16`, multicast, and `0.0.0.0/8` are refused; IPv4-mapped IPv6 is unwrapped first. CGNAT/Tailscale `100.64.0.0/10` is allowed only with `QANTARA_ALLOW_CGNAT=1`. Validated hostnames are pinned to a private address for the request while preserving the original Host authority and HTTPS server name. Probes do not follow redirects or inherit proxy variables, and backend-detection results are cached for 10 seconds with one probe in flight at a time.

The inbound Host guard accepts loopback names always, and private-LAN hosts only when a token is configured. `QANTARA_ALLOWED_HOSTS` adds exact names; `QANTARA_ALLOWED_ORIGINS` adds exact full origins when a deliberate reverse-proxy topology requires it. `/api/*` requests a browser labels `Sec-Fetch-Site: cross-site` get 403 unless their Origin is allowlisted, and `/api/backends` and `/api/backends/stream` are Origin-checked. HTML pages are served with `Cache-Control: no-cache` and a Content-Security-Policy with `connect-src 'self'`.

## Privacy

Default event logs redact transcripts, assistant text, tool parameters, and credentials. `QANTARA_BRIDGE_LOG_OUTPUT=1` is opt-in because backend-controlled stdout/stderr can contain sensitive content. Review diagnostic output before sharing it.
