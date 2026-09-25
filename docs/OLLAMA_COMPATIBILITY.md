# Ollama Compatibility

Qantara is tested against Ollama `0.32.3` as of July 24, 2026. It uses
documented Ollama endpoints rather than the CLI output format:

- `/api/chat` for the native session bridge
- `/api/tags`, `/api/version`, and `/api/ps` for discovery and diagnostics
- `/v1/models` and `/v1/chat/completions` for the direct OpenAI-compatible adapter

The stream parsers do not assume that an HTTP chunk is a complete JSON record.
They preserve split UTF-8 text, including Arabic, and handle multiple NDJSON or
SSE records delivered in one network chunk.

## Thinking models

Recent Ollama models can return hidden reasoning separately from the final
answer. Qantara never sends `message.thinking`, `reasoning`, or
`reasoning_content` to TTS.

The native Ollama bridge sets `think: false` by default for lower first-audio
latency. Set `QANTARA_OLLAMA_THINK=true` to enable reasoning while continuing
to speak only the final answer.

For the generic OpenAI-compatible adapter, set
`QANTARA_OPENAI_REASONING_EFFORT=none` when the server supports that field and
low latency is more important than reasoning. The field is omitted by default
so Qantara remains compatible with non-Ollama servers.

Models that put reasoning inline as `<think>...</think>` in the content stream
are handled too: the adapter strips the block before anything is spoken and
reports it once as a `thinking` activity. `QANTARA_OPENAI_REASONING_START`
controls the edge case of a stream that starts inside a reasoning block
without an opening tag: `auto` learns it per model after seeing a closing
`</think>` with no opening tag, `inside` always assumes it, and `outside`
never does.

## Timeouts and health

- The native bridge treats `QANTARA_OLLAMA_TIMEOUT` (default 120 s) as the
  longest silence from Ollama, not a total turn limit, and sends a `thinking`
  keep-alive to the gateway every `QANTARA_BACKEND_KEEPALIVE_SECONDS` (10 s)
  while it waits. The gateway's session adapter fails a turn only after
  `QANTARA_BACKEND_IDLE_TIMEOUT` (90 s) of silence, so long answers on slow CPU
  hardware are no longer cut off at 30 s.
- Bridge and adapter health report `degraded` when the configured model is not
  pulled (bridge) or not served (`/v1/models`, direct adapter).
- The native bridge's final text is the model's raw reply (markdown kept);
  markdown is stripped only for speech, so the spoken remainder always lines
  up with the streamed text.
- The direct adapter sends `max_tokens` (`QANTARA_OPENAI_MAX_TOKENS`, default
  512) and trims history to `QANTARA_OPENAI_HISTORY_CHAR_BUDGET` (8000
  characters) in whole exchanges; a context-length error drops the oldest
  exchange and retries once.

## Recommended local models

The setup page prioritizes these current, reasonably sized Ollama models:

1. `qwen3.5:2b` — Docker and native-bridge default
2. `qwen3.5:4b`
3. `qwen3:4b`
4. `gemma3:4b`

Older models such as `qwen2.5:3b` remain selectable when already installed.
Qantara does not pull or replace a model outside the explicit Docker
`ollama-pull` service.

See the official [Ollama chat API](https://docs.ollama.com/api/chat),
[thinking capability](https://docs.ollama.com/capabilities/thinking), and
[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
documentation for the upstream contracts.
