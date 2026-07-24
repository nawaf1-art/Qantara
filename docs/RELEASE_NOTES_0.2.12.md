# Qantara 0.2.12

This release brings Qantara back in sync with the current Ollama ecosystem and
ships the Voice-as-API work that had remained in the unmerged `0.2.11` branch.

## Highlights

- Validated both native `/api/chat` and OpenAI-compatible
  `/v1/chat/completions` streaming against Ollama `0.32.3`.
- Updated the Docker default to `qwen3.5:2b` and pinned the Ollama image to
  `0.32.3`.
- Fixed stream framing so split/coalesced network chunks and multibyte Arabic
  text cannot lose or corrupt assistant output across either backend path.
- Fixed direct-adapter cancellation races so interrupted turns are acknowledged
  and do not remain as unanswered history.
- Prevented model reasoning fields from reaching text-to-speech. The native
  bridge disables thinking by default for faster first audio.
- Added Voice-as-API endpoints for speaking, transcription, and streamed
  conversation, with the July timeout, session-recovery, validation, and
  barge-in fixes.
- Refreshed the hash-locked Python/ML stack to patched current releases and
  selected CPU-only PyTorch for Docker installs.

## Upgrade

```bash
git pull
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
```

For Docker:

```bash
docker compose pull
docker compose up --build
```

Fresh Docker setups download `qwen3.5:2b` (about 2.7 GB). Existing Ollama
volumes keep previously installed models; the explicit pull service adds the
new default without deleting them.

See [Ollama compatibility](OLLAMA_COMPATIBILITY.md),
[Voice API](VOICE_API.md), and the full [changelog](../CHANGELOG.md).
