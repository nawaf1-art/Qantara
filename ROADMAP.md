# Qantara Roadmap

Current release line: `0.4.0`

This roadmap describes direction, not a delivery promise. A feature is considered shipped only when it appears in the changelog and the public feature matrix. Proposed work should start with an issue so its scope and compatibility impact are visible.

## Current foundation

The `0.3.x` line established, and `0.4.0` corrects and hardens, Qantara as a local-first voice gateway with:

- a browser WebSocket PCM transport
- local STT and TTS provider boundaries
- explicit adapter contracts for model and agent backends
- interruption, endpointing, session continuity, and Voice-as-API
- Ollama and OpenAI-compatible paths
- optional MCP, OpenClaw, mesh, translation, and expressive-TTS experiments
- cross-platform unit CI and repeatable GitHub release artifacts

Core paths are **Beta** until broader device and deployment evidence supports a 1.0 stability promise. Optional integrations are **Experimental** unless the [feature matrix](docs/FEATURES.md) says otherwise.

## Near-term priorities

### Deployment confidence

- Browser end-to-end coverage for microphone permission, WebSocket reconnect, playback, and barge-in.
- A documented test matrix for native, Docker, reverse-proxy, and trusted-LAN modes.
- Better diagnostics that remain content-free by default.
- Model artifact manifests and preflight verification for offline or audited installs.

### Extension quality

- Provider and adapter conformance fixtures that third-party integrations can run independently.
- Clear compatibility policies for protocol/schema evolution before 1.0.
- More real-device validation for Arabic, translation, and mesh paths (the `0.4.0` mesh election fixes are unit-tested on one machine, not yet across physical devices).
- Smaller, explicit installation profiles for optional speech engines.

### Public project operations

- Keep release evidence, checksums, SBOMs, and provenance attached to each published release.
- Maintain a bounded, labeled issue backlog with good-first-issue candidates.
- Add a small, representative visual demo only after the capture is reproducible and accurately reflects a tagged build.

## Architectural work requiring design first

These items remain design-first work and are not completed by `0.4.0`:

- **Namespace consolidation:** move legacy top-level packages under `qantara.*` while preserving public imports through a staged compatibility window. See [namespace migration ADR](docs/architecture/NAMESPACE_MIGRATION_ADR.md).
- **Turn lifecycle hardening:** `0.4.0` gives each turn its own cancellation ownership (one `turn_interrupted`, one `cancel_status`, no text after an interrupt); centralizing the remaining lifecycle state is still planned. See [turn lifecycle plan](docs/architecture/TURN_LIFECYCLE_HARDENING_PLAN.md).
- **Shared stream decoder evolution:** consolidate NDJSON/SSE framing and add property/fuzz coverage beyond the bounded decoder fix. See [stream decoder plan](docs/architecture/STREAM_DECODER_HARDENING_PLAN.md).

## Later exploration

The following remain candidates rather than committed releases:

- speech-native audio-in/audio-out adapters
- Home Assistant integration through Wyoming ASR/TTS services or a conversation-API adapter (the `0.4.0` release removed the old Wyoming satellite bridge; see [Home Assistant](docs/HOMEASSISTANT.md))
- screenshot plus voice context
- an ambient announcement/event bus
- richer multi-participant coordination
- mesh frame replay protection ([#26](https://github.com/nawaf1-art/Qantara/issues/26)), once the mesh has real multi-device users
- a reviewed community provider/adapter registry
- opt-in hybrid routing to operator-selected external services

Any external-service integration must remain optional, explicit, and compatible with a fully local default deployment.

## How work moves onto the roadmap

1. Open an issue describing the user problem and deployment boundary.
2. Identify compatibility, privacy, security, and local-first implications.
3. For architecture changes, record the decision before implementation.
4. Add tests and documentation with the change.
5. Update the feature matrix and changelog only when behavior is implemented and verified.

Contributors should also read [CONTRIBUTING.md](CONTRIBUTING.md) and [GOVERNANCE.md](GOVERNANCE.md).
