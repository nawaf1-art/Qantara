# Transport Spike

Minimal gateway code for the first M0 transport spike.

Current purpose:

- accept a browser WebSocket session
- log timeline-like events
- receive inbound PCM16 frames
- send synthetic PCM16 audio back to the browser
- support simple control messages for playback testing

This code is intentionally isolated from future production gateway code until the transport assumptions are validated.

## Run

Install the minimal dependency:

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

The gateway also serves the browser spike client at:

```text
http://127.0.0.1:8765/spike
```

## Optional Piper TTS

If `piper` is installed locally and a voice model path is available, the spike can synthesize mock assistant text with Piper instead of using the synthetic tone fallback.

Set:

```bash
export QANTARA_PIPER_MODEL=/absolute/path/to/voice.onnx
```

If Piper is unavailable, the gateway falls back to the synthetic tone path automatically.

## Optional faster-whisper STT

If `faster-whisper` is installed, the spike can transcribe the recent microphone buffer.

Optional model selection:

```bash
export QANTARA_WHISPER_MODEL=base.en
```

Recommended compatibility defaults:

```bash
export QANTARA_WHISPER_DEVICE=cpu
export QANTARA_WHISPER_COMPUTE=int8
```

If faster-whisper is unavailable, the spike returns a fallback placeholder transcript instead of failing the whole session.
