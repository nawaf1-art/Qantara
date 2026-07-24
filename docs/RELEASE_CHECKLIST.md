# Release Checklist

Use this before tagging a public release.

## Latest Validation Note

The current candidate is `v0.2.12`. It combines the unmerged Voice-as-API
`0.2.11` branch with the July audit fixes, current Ollama compatibility work,
and dependency hardening. GitHub PR #15 and the absent `v0.2.11` tag must be
accounted for before publishing: merge the combined `0.2.12` candidate and
close the superseded PR rather than moving or inventing an old tag.

## Automated Checks

- [ ] `python -m unittest discover -s tests -v`
- [ ] `python -m ruff check .`
- [ ] `python -m compileall -q adapters discovery gateway providers qantara scripts`
- [ ] `python -m pip_audit -r ops/docker/requirements.txt --disable-pip`
- [ ] Build wheel and sdist with `python -m build`
- [ ] Install the wheel in a clean environment and verify `qantara.__version__`
- [ ] Run the browser inline-script syntax check
- [ ] `python scripts/bench_launch.py --json --barge-in-iterations 20 --tts-iterations 0`
- [ ] Validate `/api/version`, `/api/tags`, `/api/chat`, and `/v1/models` against the current Ollama release
- [ ] Docker build succeeds: `docker compose build`
- [ ] Docker first run reaches setup page: `docker compose up`
- [ ] CI passes on Linux, macOS, and Windows

## Manual First-Run Checks

- [ ] Fresh clone on a clean machine or VM
- [ ] Native install from `docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md`
- [ ] Docker install from README quick start
- [ ] Setup page loads at `http://localhost:8765`
- [ ] OpenAI-compatible backend can be configured against a local private/loopback URL
- [ ] Microphone prompt appears on localhost
- [ ] One English voice turn completes
- [ ] Barge-in stops playback and accepts the next turn
- [ ] Arabic turn routes to `ar_JO-kareem-medium` when that Piper voice is installed
- [ ] `/api/status`, `/api/tts`, and `/api/languages` return valid JSON

## Publication Safety

- [ ] `git status --short` is clean
- [ ] Tracked-file secret scan reports no matching file names (do not print secret values)
- [ ] No tracked local certs or model weights: `git ls-files 'ops/certs/*' 'models/piper/*.onnx'`
- [ ] `docs/SECURITY_PUBLICATION_AUDIT.md` reviewed
- [ ] Release branch targets the public repository's `main`

## GitHub Repository Setup

Recommended description:

```text
Local-first real-time voice gateway for Ollama and other local LLMs, including local AI agents: browser speech, STT, barge-in, TTS.
```

Recommended topics:

```text
voice-ai, local-first, self-hosted, ollama, speech-to-text, text-to-speech, websocket, home-assistant, piper-tts, faster-whisper
```

Before publishing:

- [ ] Set repository description
- [ ] Set topics
- [ ] Add a social preview image if available. Suggested content: Qantara wordmark, "Local voice for Ollama and local LLMs", browser mic -> gateway -> local backend diagram.
- [ ] Enable Issues
- [ ] Enable Discussions only if you intend to monitor them
- [ ] Enable private vulnerability reporting after repository is public
- [ ] Publish good-first issues from the draft list in `docs/PUBLISHING_READINESS_AUDIT.md`

## Tag and Release

Release tag:

```text
v0.2.12
```

Commands:

```bash
git tag -a v0.2.12 -m "v0.2.12 Ollama compatibility and audit hardening"
git push origin v0.2.12
gh release create v0.2.12 \
  --title "v0.2.12 - Ollama compatibility and audit hardening" \
  --notes-file docs/RELEASE_NOTES_0.2.12.md
```

Do not tag until the combined pull request is merged, CI is green, and
`VERSION`, `pyproject.toml`, `CHANGELOG.md`, `README.md`, and `ROADMAP.md`
all agree on `0.2.12`.
