# FAQ

## Is Qantara a full assistant?

No. Qantara is a voice gateway. It handles microphone capture, speech-to-text, turn-taking, barge-in, text-to-speech, and browser playback. Your LLM or agent backend handles reasoning and tools.

## Does Qantara replace Ollama?

No. Qantara can sit in front of Ollama so you can talk to local Ollama models by voice. Ollama still runs the model.

## Does it work without internet?

Yes, after dependencies and models are installed. First-time setup may need internet access to download Docker images, Python packages, STT/TTS models, and local LLMs.

## Does it send my voice to the cloud?

Not by default. Qantara's speech path is local-first, and the project does not include telemetry or Qantara-controlled cloud services. Audio goes to the local gateway and the backend endpoints you configure.

If you configure a cloud backend yourself, your text or audio may leave your machine according to that backend's behavior.

## Can I use it with OpenClaw?

Yes, as an advanced optional path. The OpenClaw bridge requires host-side OpenClaw setup and is not part of the default Docker happy path.

## Can I use it with Home Assistant?

Not as a voice satellite. The Wyoming satellite bridge was removed in `0.4.0` because Home Assistant could add it but never trigger it, and it bypassed authentication. Home Assistant automations can call Qantara's HTTP [Voice API](VOICE_API.md). See [Home Assistant](HOMEASSISTANT.md) for what was removed and possible future directions.

## Can I expose it to LAN?

Yes. Set a strong `QANTARA_AUTH_TOKEN` and use HTTPS/WSS. The token is required: without one the gateway answers only loopback requests and returns HTTP 421 to everything else. Docker binds to loopback by default, so LAN exposure must be explicit.

Do not expose Qantara directly to the public internet.

## Is it production-ready?

No. Qantara is public and usable, but still pre-1.0. It is not intended for production call centers, emergency workflows, medical use, audited enterprise compliance, or non-technical users expecting a managed commercial app.

## What models does it support?

Qantara supports backends more than specific models. The easiest path is any local OpenAI-compatible `/v1/chat/completions` server, such as Ollama, llama.cpp, LM Studio, Jan, LiteLLM, or vLLM.

Model quality, latency, and multilingual behavior depend on the model and backend you choose.
