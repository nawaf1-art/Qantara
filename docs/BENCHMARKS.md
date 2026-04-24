# Qantara Benchmarks

Public comparison methodology and internal regression budgets. The comparison story at launch (0.2.6) is anchored on one bug that other voice-AI frameworks still hit in production: interruption-path deadlocks and dropped audio.

## Current launch snapshot

Measured on 2026-04-24 with:

```bash
python scripts/bench_launch.py --arabic
```

Host: Linux 6.17 / Python 3.12.

| Metric | Samples | Median | p95 | Note |
|---|---:|---:|---:|---|
| Gateway barge-in cancel path | 20 | 0.09 ms | 0.11 ms | `cancel_active_turn` to turn completion on loopback test adapter |
| Piper TTS synthesis (`lessac`) | 3 | 1532.75 ms | 1540.51 ms | Short launch phrase, full synthesis latency |
| Piper TTS synthesis (`ar_JO-kareem-medium`) | 3 | 1800.82 ms | 1831.76 ms | Short Arabic launch phrase, full synthesis latency |

These are gateway/TTS numbers, not model-response numbers. Backend latency depends on the selected local engine, model size, hardware, and whether the model is cold or already loaded.

## Interruption-path regression

### What's being measured

When a user barges in mid-utterance:

1. How long between the cancel request and the server-side `turn_interrupted` event?
2. Does the session return to `idle` cleanly?
3. Can the next turn start and complete without hanging?

These three questions map to three real bugs still open in the leading frameworks:

| Observed failure | Source |
|---|---|
| `wait_for_playout()` ignores interruption, 5s deadlock | [livekit/agents #5359](https://github.com/livekit/agents/issues/5359) |
| TTS queue drops frames on interruption | [pipecat-ai/pipecat #4260](https://github.com/pipecat-ai/pipecat/issues/4260) |
| Partial transcripts lost on interruption | [pipecat-ai/pipecat #1694](https://github.com/pipecat-ai/pipecat/issues/1694) |

### Qantara's regression test

[`tests/test_interruption.py`](../tests/test_interruption.py) covers:

- `test_barge_in_emits_turn_interrupted_with_partial_text` — the partial assistant text is captured
- `test_barge_in_transitions_to_interrupted_then_idle` — session state flows `thinking` → `interrupted` → `idle`
- `test_no_turn_interrupted_when_nothing_streamed_yet` — no false positives
- `test_subsequent_turn_starts_cleanly_after_interruption` — the #1 deadlock pattern; second turn must start + complete in < 5s
- `test_cancel_to_turn_interrupted_under_100ms` — cancel-path latency budget: **100ms** on a loopback adapter

Run locally:

```bash
make test
```

### Head-to-head comparison (optional follow-up)

If we record a later comparison, use the same interruption scenario against Qantara, livekit-agents, and pipecat side by side. Methodology:

1. Start each framework against the same local Ollama model (`llama3.2:3b`), same Kokoro TTS, same microphone input.
2. Trigger a turn whose response is long (> 20s spoken).
3. After 3s of playback, speak a new user utterance ("stop — question about …").
4. Record: time from user speech detected → playback actually stops; whether the next turn starts; whether the captured partial is surfaced anywhere usable.

Any reproduction rig should live in `scripts/bench/` and include the exact prompts, models, and timing instrumentation so the comparison is auditable rather than "trust the video."

## Other budgets (TBD after 0.2.2)

These tables fill in as each Tier 1 item lands.

### Partial transcript latency (0.2.1)

| Metric | Budget | Measured |
|---|---|---|
| First partial emitted after `speech_start_detected` | < 500ms | — (pending real-audio harness) |
| Partial update cadence | ~400ms | ~400ms (`PARTIAL_TICK_INTERVAL_SEC`) |
| CPU cost multiplier vs single final transcription on 4s utterance (growing-buffer naïve) | < 6× | ~5.5× (research estimate; revisit after Vosk lands in 0.2.4) |

### Session state machine (0.2.1)

| Metric | Budget |
|---|---|
| `session_state_changed` emission after trigger | < 20ms |
| Idempotency under same-state calls | 0 events |

### Multi-device mesh (0.2.3, not yet implemented)

TBD — election decision time, peer-discovery latency, cross-device session continuity.

## How to read the regression numbers

- **Budgets** are ceilings; routine exceedance is a regression.
- **Measured** is what today's local-only test rigs report on a recent Linux box. Real hardware variance is huge — the launch benchmark numbers in the README are per-OS on dedicated reference machines.
- If a number moves by > 20% between releases without explanation, surface it in the PR description and consider blocking.
