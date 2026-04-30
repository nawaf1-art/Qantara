# Qantara Use Cases

Qantara is for developers who want a local-first voice layer in front of local LLMs, local AI agents, or lab automation systems.

## Local AI Voice Assistant For Ollama

Run Qantara next to Ollama and use the OpenAI-compatible setup path to talk to a local model from the browser. This is the simplest path for an Ollama voice assistant.

Typical flow:

1. Start Ollama and pull a small local model.
2. Start Qantara.
3. Choose **OpenAI-Compatible**.
4. Speak to the model in the browser.
5. Interrupt the assistant when it is going in the wrong direction.

## Voice Interface For Private Local LLMs

Use Qantara as a browser voice AI layer for llama.cpp, LM Studio, Jan, vLLM, LiteLLM, or any local server that speaks the OpenAI chat-completions shape.

This is useful when you already have a private AI assistant running locally and want voice without sending microphone audio to a cloud service.

## Browser-Based Voice Gateway For AI Agents

Qantara is a gateway, not an agent framework. It handles microphone capture, STT, turn-taking, barge-in, TTS, and playback while your backend agent handles reasoning and tools.

This keeps voice concerns separate from agent runtime concerns.

## Voice Layer For OpenClaw-Style Agent Systems

Advanced users can connect Qantara to OpenClaw-style local agents through the optional bridge path. This is useful when the agent already exists and you want a local voice channel over it.

The OpenClaw bridge requires host setup and is not part of the default Docker happy path.

## Home Or Lab AI Assistant

Use Qantara on a workstation, mini PC, or local server as a LAN voice gateway for experiments around home AI, lab automation, and private assistant workflows.

For LAN use, configure HTTPS/WSS and `QANTARA_AUTH_TOKEN`. Do not expose Qantara directly to the public internet.

## Privacy-First Alternative To Cloud Voice Assistants

Qantara has no analytics SDK, no hosted Qantara account, and no Qantara-controlled cloud service. Speech processing runs locally by default, and the gateway connects only to the backend endpoints you configure.

Model downloads may contact their upstream model hosts on first use. See [SUPPLY_CHAIN.md](SUPPLY_CHAIN.md).

## Developer Testbed For Real-Time Voice Agents

Use Qantara to test voice-agent behaviors such as:

- Endpointing and auto-submit timing
- Barge-in handling
- Local STT/TTS provider swaps
- OpenAI-compatible backend prompts
- MCP voice-control workflows
- Multi-device and LAN experiments

## Smart Home And Home Assistant Experiments

Qantara includes an experimental Wyoming satellite path for Home Assistant Assist workflows. Treat this as a technical integration path for local labs, not a polished commercial smart-home product.
