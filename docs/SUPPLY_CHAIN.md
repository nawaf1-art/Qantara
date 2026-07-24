# Supply Chain & Model Integrity

Qantara runs AI models locally. This document explains what gets downloaded, from where, and how to verify integrity. Review this before using Qantara in a hardened environment.

## What Qantara downloads

| Artifact | Source | Triggered by | Size |
|---|---|---|---|
| `faster-whisper` model (e.g., `base.en`) | HuggingFace Hub (`Systran/faster-whisper-*`) | First STT call | ~100 MB |
| `Kokoro-82M` model assets + voice packs | HuggingFace Hub (`hexgrad/Kokoro-82M`) | First Kokoro TTS call | ~350 MB |
| Piper voices (`en_US-lessac-medium.onnx` etc.) | You download manually to `models/piper/` | Pre-installed by user | ~20 MB each |
| Ollama model (`qwen3.5:2b` by default in Docker) | `registry.ollama.ai` | `docker compose up` or first run | ~2.7 GB |
| Python/ML dependencies | PyPI via `pip` | `pip install -r requirements.txt` or Docker build | Several GB in the Docker image because speech packages include large ML wheels |

## Who verifies integrity

- **HuggingFace Hub downloads** (faster-whisper, Kokoro): the `huggingface_hub` library (used internally by `faster-whisper` and `kokoro`) verifies files by content-addressed ETags. Files are named by commit SHA; a tampered repo would require either HuggingFace compromise or a downgrade attack.
- **PyPI installs**: pip verifies the exact versions and wheel hashes committed in `gateway/transport_spike/requirements.txt`. The CPU-only PyTorch index and version are pinned in the corresponding `.in` file.
- **Ollama images**: Ollama models are content-addressed by SHA256 internally; the Ollama registry verifies on pull.
- **Docker images**: Compose pins the validated `ollama/ollama:0.32.3` version tag. Hardened deployments can pin the matching architecture-specific digest for fully reproducible pulls (`ollama/ollama@sha256:...`).
- **Piper voices**: you download manually. Verify against the [Piper voices release](https://huggingface.co/rhasspy/piper-voices) SHA256 sums published with each voice.

## What Qantara does *not* yet do

- No first-party SHA256SUMS file for downloaded artifacts. We trust the upstream providers' integrity mechanisms (above). Adding a first-party verifier is tracked for v0.2.x; until then, follow the upstream-verification guidance below.
- No Sigstore / reproducible-build attestations on Qantara itself.
- No SBOM generation in CI.

These are hardening items for v0.3.x+.

## Regenerating Python lock files

The two runtime lock files are universal locks generated for Qantara's minimum
supported Python 3.11 from their adjacent `.in` files:

```bash
uv pip compile --universal --generate-hashes --python-version 3.11 \
  --index-strategy unsafe-best-match --emit-index-url \
  --output-file gateway/transport_spike/requirements.txt \
  gateway/transport_spike/requirements.in

uv pip compile --universal --generate-hashes --python-version 3.11 \
  --index-strategy unsafe-best-match --emit-index-url \
  --output-file ops/docker/requirements.txt \
  ops/docker/requirements.in
```

The `unsafe-best-match` index strategy is required because the exact
`torch==2.13.0+cpu` wheel comes from PyTorch's CPU index. Direct versions and
all resolved artifact hashes remain pinned in the generated files.

## Manual verification (air-gapped or audit contexts)

If you need to verify downloads yourself before allowing network egress from the gateway host:

1. **faster-whisper**: pre-download the model on a trusted machine using the `huggingface_hub` CLI, verify the SHA256 against the HuggingFace Hub API (`https://huggingface.co/api/models/<repo>/revision/<sha>`), then copy into the target host's HuggingFace cache directory (`~/.cache/huggingface/hub/`).
2. **Kokoro**: same process, targeting `hexgrad/Kokoro-82M`.
3. **Piper**: download the voice .onnx and .json from `https://huggingface.co/rhasspy/piper-voices`, verify against the published sums, place in `models/piper/`.
4. **Ollama**: `ollama pull <model>` on a trusted machine, then use `ollama cp` / copy the `~/.ollama/models/` directory.
5. Run Qantara with network egress disabled; all model calls should succeed from local cache.

## Reporting a supply-chain concern

If you suspect tampering or a malicious artifact in Qantara's own release surface (not an upstream dependency), follow [SECURITY.md](../SECURITY.md).
