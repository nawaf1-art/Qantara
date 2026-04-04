# Run Transport Spike

## Goal

Run the current transport spike in a consistent way and record the results in the transport notes file.

## Prerequisites

- Python 3 available
- browser with microphone permission support
- headset preferred

Optional:

- `piper-tts` installed in the repo `.venv`
- `QANTARA_PIPER_MODEL` pointing to a Piper voice model, or the default local test model at `models/piper/en_US-lessac-medium.onnx`
- `QANTARA_ADAPTER=mock` or `QANTARA_ADAPTER=runtime_skeleton`

## Start Gateway

From the repo root:

```bash
pip install -r gateway/transport_spike/requirements.txt
python3 gateway/transport_spike/server.py
```

Open:

```text
http://127.0.0.1:8765/spike
```

If the default port is already in use:

```bash
QANTARA_SPIKE_PORT=8899 ./.venv/bin/python gateway/transport_spike/server.py
```

Then open:

```text
http://127.0.0.1:8899/spike
```

For LAN access from another device:

```bash
QANTARA_SPIKE_HOST=0.0.0.0 QANTARA_SPIKE_PORT=8899 ./.venv/bin/python gateway/transport_spike/server.py
```

Then open:

```text
http://<your-lan-ip>:8899/spike
```

## Test Sequence

### 1. Connection

- click `Connect`
- confirm the socket state changes to `connected`
- confirm the gateway prints session events

### 2. Playback

- click `Request Tone`
- confirm playback starts
- click `Clear Playback`
- confirm playback stops quickly

If Piper is configured:

- submit a mock turn and confirm spoken output is produced through Piper instead of tone fallback
- confirm the browser `TTS` status changes to `piper`
- note the browser `First Audio` measurement

### 3. Microphone Transport

- click `Start Mic`
- speak for a few seconds
- confirm `Frames Sent` continues increasing
- confirm `VAD` flips between `speech` and `silence`
- confirm the gateway logs `input_audio_frame_received` events

### 4. Mock Turn Flow

- enter sample text in the mock input
- click `Mock Turn`
- confirm assistant text deltas appear in the browser
- confirm final assistant text appears
- confirm playback occurs afterward

### 5. Recent Audio Transcription

- start the microphone
- speak a short sentence
- click `Transcribe Recent Audio`
- confirm a transcript result appears

If faster-whisper is not installed:

- confirm the fallback transcript result appears instead of a hard failure

### 6. Disconnect Recovery

- click `Disconnect`
- reconnect again
- note whether the browser and gateway recover predictably

### 7. Playback Clear Timing

- start a `Mock Turn`
- click `Clear Playback` while audio is active
- note the browser `Clear Ack` measurement
- note whether audible stop feels immediate enough for future barge-in work

## What To Record

Record findings in:

- [`experiments/notes/transport-spike.md`](notes/transport-spike.md)

Minimum notes:

- browser used
- whether headset or speakers were used
- playback startup feel
- whether `Clear Playback` was responsive
- observed `First Audio` timing for Piper
- observed `Clear Ack` timing
- whether VAD threshold felt too sensitive or too weak
- whether the transcription result was useful or only placeholder fallback
- whether WebSocket transport still looks acceptable for M1

## Failure Conditions To Watch

- erratic frame cadence
- repeated disconnects
- stale playback after clear
- browser mic permission instability
- VAD flipping constantly during silence
- immediate evidence that WebRTC is required sooner than expected
