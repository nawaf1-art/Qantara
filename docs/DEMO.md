# Qantara Demo Runbook

Use this to record the public-launch clip. Target length: 45-60 seconds.

## Setup

Start a local OpenAI-compatible backend, then run Qantara on LAN HTTPS:

```bash
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=8899 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
QANTARA_ADAPTER=openai_compatible \
QANTARA_OPENAI_BASE_URL=http://127.0.0.1:11434 \
QANTARA_OPENAI_MODEL=qwen2.5:3b \
./.venv/bin/python gateway/transport_spike/server.py
```

Open:

```text
https://<lan-ip>:8899/spike
```

Allow microphone access. Use a headset for the cleanest barge-in recording.

## Shot List

1. Show the browser voice UI connected to a local backend.
2. Ask in English: "Give me one sentence about Qantara."
3. Interrupt while it is speaking: "Stop. Say it shorter."
4. Ask in Arabic: "تتكلم عربي؟"
5. Confirm the debug log shows `tts status: piper:ar_JO-kareem-medium`.
6. End on the backend status showing the local model.

## What To Capture

- Full-duplex behavior: the assistant can be interrupted mid-sentence.
- State transitions: listening, thinking, speaking, idle.
- Local-first backend: OpenAI-compatible URL points at LAN or loopback.
- Arabic path: transcript is `[AR]`, reply is Arabic, TTS voice is Kareem.

## Acceptance

- No microphone permission error.
- No mock assistant response.
- No premature `idle` before playback finishes.
- Arabic audio uses `ar_JO-kareem-medium` and feels close to the 1.3x baseline.
- Clip does not expose tokens, private hostnames outside LAN, or unrelated browser tabs.
