# Marketing Copy

Use this file as copy/paste material for launch posts. Keep claims honest and update examples when new demos or screenshots exist.

## Short GitHub Description

Local-first real-time voice gateway for Ollama, OpenAI-compatible local LLMs, MCP, and local AI agents: browser mic, STT, TTS, and barge-in.

## Long GitHub Description

Qantara is a local-first, real-time voice gateway for developers building private AI assistants, Ollama agents, local LLM apps, OpenClaw-style agents, and self-hosted voice AI systems. It connects a browser microphone to local STT, a local backend, local TTS, and browser playback over WebSocket. It is a voice layer, not a full assistant framework.

## Reddit Post Draft

Title:

```text
I built Qantara: a local-first browser voice gateway for Ollama and local LLM agents
```

Body:

```text
I have been building Qantara, an Apache-2.0 local-first voice gateway for Ollama, OpenAI-compatible local LLM servers, MCP tools, and local AI agents.

It is not a full assistant framework. It is the real-time voice layer: browser mic capture, local STT, endpointing, barge-in, backend adapter, local TTS, and browser playback.

Current status: pre-1.0 but usable. The stable path is browser voice UI + WebSocket pipeline + local STT/TTS + OpenAI-compatible backends. MCP and Home Assistant/Wyoming paths are experimental.

Repo: https://github.com/nawaf1-art/Qantara

I would especially like feedback from people building local voice assistants, Ollama agents, private AI assistants, or self-hosted voice AI setups.
```

## Hacker News "Show HN" Draft

```text
Show HN: Qantara, a local-first browser voice gateway for Ollama and local LLMs

Qantara is an Apache-2.0 real-time voice gateway for local AI systems. It connects a browser microphone to local STT, a local LLM or agent backend, local TTS, and browser playback over WebSocket.

The goal is to make it easier to add voice to Ollama, OpenAI-compatible local servers, MCP tools, and local agent runtimes without turning the voice layer into the assistant framework.

Current stable pieces: browser voice UI, local STT/TTS, barge-in, Docker/local setup, OpenAI-compatible backend path. MCP and Home Assistant/Wyoming are experimental.

Repo: https://github.com/nawaf1-art/Qantara
```

## X/Twitter Post

```text
I released Qantara: a local-first real-time voice gateway for Ollama, OpenAI-compatible local LLMs, MCP tools, and local AI agents.

Browser mic -> local STT -> local backend -> local TTS -> browser playback, with barge-in.

Apache-2.0, pre-1.0, honest status labels:
https://github.com/nawaf1-art/Qantara
```

## LinkedIn Post

```text
I am releasing Qantara, a local-first real-time voice gateway for developers building private AI assistants and local LLM workflows.

Qantara is not another agent framework. It is the voice layer: browser microphone capture, local speech-to-text, endpointing, interruption, backend adapters, local text-to-speech, and browser playback.

It works best today with local OpenAI-compatible backends such as Ollama, llama.cpp, LM Studio, Jan, LiteLLM, and vLLM. MCP and Home Assistant/Wyoming integrations are included as experimental paths.

Repo: https://github.com/nawaf1-art/Qantara
```

## Product Hunt Style Tagline

```text
Local-first voice gateway for Ollama and private AI agents.
```

## Demo Video Ideas

1. Start Docker, open the browser, select Demo, and prove the microphone and playback path.
2. Connect Qantara to Ollama through the OpenAI-compatible setup page and ask a local model a question.
3. Interrupt the assistant mid-answer to demonstrate barge-in.
4. Show local-first posture: localhost binding, auth token for LAN, no analytics, and private backend URL checks.
5. Show the MCP path as experimental: configure a simple MCP chat tool and speak through it.

## Screenshot And GIF Ideas

1. Setup page with detected backend cards.
2. Voice mode with captions and active orb.
3. Backend configuration form for OpenAI-compatible local servers.
4. Debug panel showing latency/backend state.
5. LAN/auth token prompt for local network testing.
