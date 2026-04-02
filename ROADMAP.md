# Roadmap

Current version: `0.1.0-alpha.1`

## Current Position

Qantara has completed its first meaningful alpha checkpoint:

- secure LAN browser spike is working over `HTTPS/WSS`
- `faster-whisper` is validated as the first STT candidate
- `Piper` is validated as the first TTS candidate
- first-chunk TTS playback is improved to about `1.50s`
- session-oriented backend adapter path is working end to end
- endpoint-ready to submit flow is validated with the local fake backend
- end-to-end cancel is validated

This is the first versioned milestone because the project has moved beyond research and isolated transport checks into a real, validated gateway path.

## R0: Alpha Checkpoint `0.1.0-alpha.1`

Status: complete

Outcome:

- browser client can capture audio and speak backend-driven responses
- gateway can transcribe recent speech and submit it as a turn
- assistant output streams through a real adapter path
- local playback can be cleared immediately
- fake backend proves the first concrete backend contract

## R1: Hands-Free M1 Baseline

Status: next

Goals:

- auto-submit recent speech on endpoint-ready instead of requiring a button
- tighten VAD thresholds and silence timing from observed runs
- reduce duplicate or noisy endpoint transitions
- improve reconnect behavior after disconnects
- persist session-level event logs for comparison across runs

Exit target:

- one browser user can speak naturally without pressing submit
- endpointing is stable enough for repeated short turns

## R2: Lower-Latency Spoken Response

Status: planned

Goals:

- keep early chunk playback as the baseline behavior
- reduce first spoken chunk latency below the current `~1.5s`
- decide whether `Piper` remains the default TTS path or becomes the fallback
- measure chunk-to-chunk cadence more explicitly

Exit target:

- spoken responses feel faster and more conversational on the target hardware

## R3: Real Backend Integration

Status: planned

Goals:

- choose the first real session-oriented backend target
- implement the real adapter against that backend
- keep environment-specific values out of the core design
- validate session bootstrap, turn stream, and cancel against that backend

Exit target:

- Qantara works with one real backend target beyond the local fake backend

## R4: Hard Barge-In

Status: planned

Goals:

- distinguish local playback clear from backend generation cancel
- support interruption-aware history handling
- validate repeated interruption across longer responses
- harden cancel behavior under overlapping turns

Exit target:

- interruption semantics are reliable enough for real conversational use

## R5: Security And Operational Hardening

Status: planned

Goals:

- client auth or signed session tokens
- safer LAN deployment defaults
- audit and replay traces
- confirmation gates for risky downstream actions

Exit target:

- internal LAN deployment is safer and easier to operate
