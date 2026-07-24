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
