# Gateway Runtime

This directory contains Qantara's aiohttp gateway runtime and WebSocket transport.
The `transport_spike` package name is historical; the code is now the primary
local gateway used by the browser client.

Current purpose:

- accept a browser WebSocket session
- emit timeline-style events
- receive inbound PCM16 frames
- run speech-to-text, backend adapter turns, text-to-speech, and playback
- support turn-taking, interruption, language routing, and LAN access

## Run

Install dependencies:

```bash
pip install -r gateway/transport_spike/requirements.txt
```

Start the gateway:

```bash
python3 gateway/transport_spike/server.py
```

The gateway listens on:

```text
ws://127.0.0.1:8765/ws
```

The gateway also serves the browser client at:

```text
http://127.0.0.1:8765/spike
```

## Optional Piper TTS

If Piper is installed locally and a voice model path is available, Qantara can synthesize assistant text with Piper instead of using the synthetic fallback.

Set:

```bash
export QANTARA_PIPER_MODEL=/absolute/path/to/voice.onnx
```

If Piper is unavailable, the gateway falls back to the synthetic tone path automatically.

## Optional faster-whisper STT

If `faster-whisper` is installed, Qantara can transcribe the recent microphone buffer.

Optional model selection:

```bash
export QANTARA_WHISPER_MODEL=base.en
```

Recommended compatibility defaults:

```bash
export QANTARA_WHISPER_DEVICE=cpu
export QANTARA_WHISPER_COMPUTE=int8
```

If faster-whisper is unavailable, Qantara returns a fallback placeholder transcript instead of failing the whole session.
