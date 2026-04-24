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
| `QANTARA_TLS_CERT` | unset | Path to local TLS certificate |
| `QANTARA_TLS_KEY` | unset | Path to local TLS private key |
| `QANTARA_AUTH_TOKEN` | unset | Optional bearer token for `/ws`, `/api/configure`, and translation mode |
| `QANTARA_ADMIN_TOKEN` | unset | Optional bearer token for `/api/admin/runtime`; endpoint is disabled when unset |

## Backend Variables

Recommended OpenAI-compatible path:

| Variable | Example | Purpose |
|---|---|---|
| `QANTARA_ADAPTER` | `openai_compatible` | Selects direct chat-completions adapter |
| `QANTARA_OPENAI_BASE_URL` | `http://127.0.0.1:11434` | Base URL for the local backend |
| `QANTARA_OPENAI_MODEL` | `qwen2.5:3b` | Model id |
| `QANTARA_OPENAI_API_KEY` | `not-needed` | Optional bearer token for compatible servers that require one |

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
| `QANTARA_KOKORO_DEVICE` | provider default | Kokoro device |
| `QANTARA_DEFAULT_SPEECH_RATE` | `1.0` | User-level speech-rate multiplier |

Piper voices are downloaded with:

```bash
scripts/fetch_piper_voices.sh
```

Downloaded `.onnx` files and local certs are ignored by git.

## URL Safety

The setup page and `/api/configure` reject public backend URLs. Use loopback, private LAN, or container-network addresses. This is intentional SSRF protection.

## Configuration Precedence

When multiple sources are used, prefer this order:

1. Environment variables for deployment
2. Setup page for interactive local use
3. `qantara.yml` for local repeatability
4. Built-in defaults
