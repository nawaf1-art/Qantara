# Ollama Session Backend

This local bridge implements Qantara's generic session HTTP path ([`protocols/session-gateway-http.md`](../../protocols/session-gateway-http.md)) against native Ollama streaming. Its adapter-facing behavior follows [`adapters/CONTRACT.md`](../../adapters/CONTRACT.md) and [`protocols/agent.md`](../../protocols/agent.md).

The direct OpenAI-compatible Ollama path is simpler for most users. Use this bridge when the Qantara session contract or native Ollama stream behavior is specifically desired.

## Defaults

- Ollama base URL: `http://127.0.0.1:11434`
- model: `qwen3.5:2b`
- thinking: disabled for lower voice latency
- bridge bind: `127.0.0.1:19120`

Set `QANTARA_OLLAMA_THINK=true` to include Ollama reasoning internally. Reasoning fields and inline `<think>` blocks are never sent to TTS or stored in history; the bridge reports them once per turn as a `thinking` activity.

Other behavior:

- the streamed text is sent unmodified, and `assistant_text_final` equals the joined deltas;
- `QANTARA_OLLAMA_TIMEOUT` (default 120) is an idle bound on the Ollama stream, not a total bound;
- while Ollama is silent (model load, long prefill) the bridge sends a `thinking` activity at least every `QANTARA_BACKEND_KEEPALIVE_SECONDS` (default 10), so the gateway's `QANTARA_BACKEND_IDLE_TIMEOUT` does not fire;
- `/health` reports `degraded` when the configured model is not pulled.

## Recommended managed run

```bash
./.venv/bin/python cli.py --backend ollama --model qwen3.5:2b
```

The CLI starts and stops the loopback bridge automatically.

## Manual bridge run

```bash
QANTARA_REAL_BACKEND_HOST=127.0.0.1 \
QANTARA_REAL_BACKEND_PORT=19120 \
QANTARA_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
QANTARA_OLLAMA_MODEL=qwen3.5:2b \
./.venv/bin/python gateway/ollama_session_backend/server.py
```

Then start the gateway with:

```bash
QANTARA_ADAPTER=session_gateway_http \
QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 \
./.venv/bin/python gateway/transport_spike/server.py
```

## Cancellation

Cancellation closes the bridge's Ollama request at once, whether Ollama is still loading or already streaming, and the event stream ends with `cancel_acknowledged`. The gateway independently stops playback and can force-cancel its in-flight task after the configured grace period.

See [`docs/OLLAMA_COMPATIBILITY.md`](../../docs/OLLAMA_COMPATIBILITY.md) for validated versions, stream behavior, and model guidance.
