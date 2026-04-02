"""Simulate the browser VAD state machine with realistic RMS patterns.

Tests whether the tuned thresholds (start=0.035, stop=0.012, EMA alpha=0.3,
stop_frames=7, endpoint_silence=600ms) produce stable endpointing.
"""

import math

# Browser VAD parameters (from index.html)
VAD_START_RMS = 0.035
VAD_STOP_RMS = 0.012
VAD_START_FRAMES = 3
VAD_STOP_FRAMES = 7
ENDPOINT_SILENCE_MS = 600
RMS_EMA_ALPHA = 0.3

# AudioContext frame cadence: 2048 samples at 48kHz = ~42.67ms per frame
FRAME_MS = 42.67


def simulate_vad(rms_sequence: list[float]) -> list[dict]:
    """Run the VAD state machine over a sequence of raw RMS values."""
    smoothed_rms = 0
    vad_speech = False
    speech_frames = 0
    silence_frames = 0
    endpoint_pending = False
    endpoint_pending_at = None
    events = []
    time_ms = 0

    for raw_rms in rms_sequence:
        smoothed_rms = RMS_EMA_ALPHA * raw_rms + (1 - RMS_EMA_ALPHA) * smoothed_rms
        rms = smoothed_rms

        if vad_speech:
            if rms > VAD_STOP_RMS:
                silence_frames = 0
            else:
                silence_frames += 1
            if silence_frames >= VAD_STOP_FRAMES:
                vad_speech = False
                silence_frames = 0
                speech_frames = 0
                events.append({"time_ms": round(time_ms), "event": "silence", "rms": round(rms, 4)})
                endpoint_pending = True
                endpoint_pending_at = time_ms
        else:
            if rms > VAD_START_RMS:
                speech_frames += 1
            else:
                speech_frames = 0
            if speech_frames >= VAD_START_FRAMES:
                vad_speech = True
                speech_frames = 0
                silence_frames = 0
                events.append({"time_ms": round(time_ms), "event": "speech", "rms": round(rms, 4)})
                if endpoint_pending:
                    endpoint_pending = False
                    events.append({"time_ms": round(time_ms), "event": "endpoint_cancelled"})

        # Check endpoint timer
        if endpoint_pending and (time_ms - endpoint_pending_at) >= ENDPOINT_SILENCE_MS:
            events.append({"time_ms": round(time_ms), "event": "endpoint_ready"})
            endpoint_pending = False

        time_ms += FRAME_MS

    # Final endpoint check
    if endpoint_pending:
        remaining = ENDPOINT_SILENCE_MS - (time_ms - endpoint_pending_at)
        if remaining <= 0:
            events.append({"time_ms": round(time_ms), "event": "endpoint_ready"})

    return events


def generate_speech_pattern(
    duration_frames: int,
    base_rms: float = 0.08,
    noise: float = 0.02,
) -> list[float]:
    """Generate RMS values simulating speech (with natural variation)."""
    return [
        max(0, base_rms + noise * math.sin(i * 0.5) + noise * 0.5 * math.sin(i * 1.3))
        for i in range(duration_frames)
    ]


def generate_silence(duration_frames: int, noise_floor: float = 0.005) -> list[float]:
    """Generate RMS values simulating silence."""
    return [noise_floor + 0.002 * math.sin(i * 0.3) for i in range(duration_frames)]


def generate_pause(duration_frames: int, rms: float = 0.015) -> list[float]:
    """Generate a brief intra-sentence pause (borderline RMS)."""
    return [rms + 0.003 * math.sin(i * 0.7) for i in range(duration_frames)]


def test_simple_utterance():
    """Test: speak for 2 seconds, then silence. Should produce exactly one endpoint."""
    print("TEST: Simple utterance (2s speech + silence)")
    rms = generate_silence(5) + generate_speech_pattern(47) + generate_silence(30)
    events = simulate_vad(rms)
    for e in events:
        print(f"  {e['time_ms']:>6}ms  {e['event']:<20} {e.get('rms', '')}")
    endpoints = [e for e in events if e["event"] == "endpoint_ready"]
    speech_starts = [e for e in events if e["event"] == "speech"]
    print(f"  Result: {len(speech_starts)} speech starts, {len(endpoints)} endpoints")
    assert len(endpoints) == 1, f"Expected 1 endpoint, got {len(endpoints)}"
    assert len(speech_starts) == 1, f"Expected 1 speech start, got {len(speech_starts)}"
    print("  PASS")
    print()


def test_two_sentences():
    """Test: two sentences with a 500ms pause. Should produce 1 endpoint (pause too short)."""
    print("TEST: Two sentences with 500ms pause")
    pause_frames = int(500 / FRAME_MS)
    rms = (
        generate_silence(5)
        + generate_speech_pattern(30)
        + generate_pause(pause_frames)
        + generate_speech_pattern(30)
        + generate_silence(30)
    )
    events = simulate_vad(rms)
    for e in events:
        print(f"  {e['time_ms']:>6}ms  {e['event']:<20} {e.get('rms', '')}")
    endpoints = [e for e in events if e["event"] == "endpoint_ready"]
    print(f"  Result: {len(endpoints)} endpoints")
    print(f"  {'PASS' if len(endpoints) <= 2 else 'CONCERN: over-segmentation'}")
    print()


def test_brief_noise_spike():
    """Test: silence with a brief noise spike. Should NOT trigger speech."""
    print("TEST: Brief noise spike in silence")
    rms = generate_silence(10) + [0.05, 0.04] + generate_silence(20)
    events = simulate_vad(rms)
    for e in events:
        print(f"  {e['time_ms']:>6}ms  {e['event']:<20} {e.get('rms', '')}")
    speech_starts = [e for e in events if e["event"] == "speech"]
    print(f"  Result: {len(speech_starts)} false speech starts")
    assert len(speech_starts) == 0, f"Expected 0 false triggers, got {len(speech_starts)}"
    print("  PASS")
    print()


def test_hesitant_speech():
    """Test: speech with mid-word dips. Should not over-segment."""
    print("TEST: Hesitant speech with RMS dips")
    rms = (
        generate_silence(5)
        + generate_speech_pattern(10, base_rms=0.06)
        + [0.02, 0.018, 0.015, 0.013]  # brief dip
        + generate_speech_pattern(15, base_rms=0.07)
        + [0.02, 0.016, 0.014, 0.013, 0.012]  # another dip
        + generate_speech_pattern(10, base_rms=0.065)
        + generate_silence(30)
    )
    events = simulate_vad(rms)
    for e in events:
        print(f"  {e['time_ms']:>6}ms  {e['event']:<20} {e.get('rms', '')}")
    endpoints = [e for e in events if e["event"] == "endpoint_ready"]
    speech_starts = [e for e in events if e["event"] == "speech"]
    print(f"  Result: {len(speech_starts)} speech starts, {len(endpoints)} endpoints")
    print(f"  {'PASS' if len(endpoints) == 1 else 'CONCERN: over-segmented hesitant speech'}")
    print()


def test_endpoint_timing():
    """Test: verify endpoint fires at correct timing after silence."""
    print("TEST: Endpoint timing accuracy")
    rms = generate_silence(3) + generate_speech_pattern(20) + generate_silence(40)
    events = simulate_vad(rms)
    silence_event = next((e for e in events if e["event"] == "silence"), None)
    endpoint_event = next((e for e in events if e["event"] == "endpoint_ready"), None)
    if silence_event and endpoint_event:
        gap = endpoint_event["time_ms"] - silence_event["time_ms"]
        print(f"  Silence at: {silence_event['time_ms']}ms")
        print(f"  Endpoint at: {endpoint_event['time_ms']}ms")
        print(f"  Gap: {gap}ms (target: {ENDPOINT_SILENCE_MS}ms)")
        print(f"  {'PASS' if abs(gap - ENDPOINT_SILENCE_MS) < FRAME_MS * 2 else 'FAIL: timing off'}")
    else:
        print("  FAIL: missing events")
    print()


if __name__ == "__main__":
    test_simple_utterance()
    test_two_sentences()
    test_brief_noise_spike()
    test_hesitant_speech()
    test_endpoint_timing()
