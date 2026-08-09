# Benchmarks and Regression Budgets

Qantara does not publish a current cross-project performance comparison. Backend, STT, and TTS latency depends heavily on hardware, model, runtime, cache state, audio, and configuration. This file preserves one historical local snapshot and defines reproducibility requirements for future measurements.

## Historical snapshot (not a current release claim)

The following values were recorded on 2026-04-24 from repository commit `59149657915444c13e64b23fd0efdbf67b1dc259` using:

```bash
python scripts/bench_launch.py --arabic
```

Recorded environment: Linux 6.17 and Python 3.12. CPU model, memory, power mode, Piper build, voice artifact hashes, thermal state, and cold/warm cache details were not recorded. Sample counts are too small for broad conclusions.

| Metric | Samples | Median | p95 | Historical scope |
|---|---:|---:|---:|---|
| Gateway cancel path | 20 | 0.09 ms | 0.11 ms | In-process loopback test adapter; not end-to-end speech interruption |
| Piper `lessac` synthesis | 3 | 1532.75 ms | 1540.51 ms | One short phrase, full synthesis |
| Piper `ar_JO-kareem-medium` synthesis | 3 | 1800.82 ms | 1831.76 ms | One short Arabic phrase, full synthesis |

These numbers are retained for historical traceability only. They are not advertised as `0.3.1` performance, hardware guidance, or evidence of superiority over another project.

## Current regression checks

The automated suite checks behavior and bounded timing where deterministic:

- cancellation cannot wait indefinitely for an uncooperative adapter
- interrupted output is gated from later playback/text delivery
- the session can accept a subsequent turn after cancellation
- stream parsing preserves fragmented/coalesced records and multibyte UTF-8
- oversized stream lines, control messages, and frames fail within explicit limits

Run:

```bash
python -m unittest tests.test_interruption tests.test_streaming -v
```

Test timeouts are regression ceilings for synthetic conditions, not user-facing latency benchmarks.

## Requirements for a new public benchmark

A new result should include:

- exact Qantara commit/tag and dirty-tree state
- exact command and benchmark script committed in the repository
- OS/kernel, Python, package lock, container/image digests, and provider versions
- CPU/GPU model, RAM/VRAM, power mode, and relevant device settings
- model and voice identifiers plus immutable revisions/hashes where available
- input text/audio fixture hashes and language
- cold versus warm methodology and discarded warm-up runs
- sample count, raw result file, median/p95 calculation, failures, and variance
- whether the measurement is in-process, loopback HTTP, LAN, or browser end-to-end

Comparisons with other projects must use the same hardware, fixtures, providers, backend model, cache state, and measurement boundary. Open upstream issues or anecdotal behavior are not benchmark data.

## Candidate measurements

- speech detected to playback stopped during barge-in
- endpoint detected to final transcript
- backend first user-facing token
- TTS request to first audio and total synthesis
- next-turn readiness after interruption/disconnect
- memory growth across long sessions and malformed/oversized streams

Until those harnesses and provenance records exist, documentation should describe mechanisms and test coverage rather than quote performance values.
