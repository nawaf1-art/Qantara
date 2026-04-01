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
