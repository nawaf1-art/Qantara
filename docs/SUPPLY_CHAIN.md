# Supply Chain and Artifact Integrity

Qantara combines ordinary Python packages, large ML wheels, speech/model artifacts, container images, and operator-supplied runtimes. This document distinguishes what the repository pins from what still depends on an upstream mutable reference.

## Dependency surfaces

| Surface | Current safeguard | Remaining operator consideration |
|---|---|---|
| Base Python package | Narrow runtime dependency range in `pyproject.toml`; CI strictly audits the resolved third-party base set | Normal package installs resolve compatible releases at install time |
| Optional extras | Minimum versions with major-version caps (for example `zeroconf>=0.150,<1`, `mcp>=1.28,<2`) so Qantara can share an environment with other tools; exact versions live only in the lock files | Dependabot ignores `mcp` major versions until the MCP 2.x client migration |
| Development/test tools | Exact versions in the `dev` extra and CI (`build`, `ruff`, `twine`, `pip-audit`), synchronized with `.pre-commit-config.yaml`; CI upgrades to a reviewed `pip` version before installing | Update intentionally through reviewed dependency PRs |
| Full native speech lock | Generated, version-and-hash locked `gateway/transport_spike/requirements.txt` covering CPython 3.11/3.12 on Linux x86_64/aarch64, Windows amd64 and macOS arm64 | Regenerate with `scripts/lock_requirements.py`; CI runs `scripts/check_lock_hashes.py` |
| Docker Python/ML lock | Same lock as `ops/docker/requirements.txt`; pip uses `--require-hashes`; the image is built and smoke-tested on amd64 and arm64 in CI | Regenerate with `scripts/lock_requirements.py` |
| Docker Python base | Multi-platform image index pinned by SHA256 digest in `Dockerfile`; Dependabot ignores Python minor/major bumps (Kokoro requires <3.13) | Debian packages installed during build still come from the configured live apt repository |
| Docker installer | Exact PyPI `pip` wheel URL and SHA256 in `Dockerfile` | Review the official PyPI artifact and audit result before updating |
| spaCy English model in Docker | Exact model release URL and SHA256 fragment | Review compatibility when spaCy changes |
| Ollama container | `ollama/ollama:0.32.3` plus its reviewed multi-architecture manifest digest | Review and update the tag and digest together; Dependabot may propose digest refreshes |
| GitHub Actions | Every third-party Action invocation is pinned to a full commit SHA with a version comment | Dependabot proposes reviewed updates |

## Model downloads

| Artifact | Typical source | Trigger |
|---|---|---|
| faster-whisper model | Hugging Face Hub | First STT model load unless pre-cached |
| Kokoro model/voices | Hugging Face Hub or provider dependency | First TTS use unless pre-cached; with `QANTARA_OFFLINE=1` or `HF_HUB_OFFLINE=1` a missing spaCy model fails clearly instead of being downloaded |
| Piper voice and config | `scripts/fetch_piper_voices.sh`: a pinned `rhasspy/piper-voices` revision with a SHA-256 checked for every file (mismatches are deleted), or an operator-selected source | Manual installation |
| Ollama model | Ollama registry | `ollama pull` or Compose initialization |
| Chatterbox assets | Its configured runtime/upstream | Optional provider initialization |

Qantara does not yet maintain a first-party manifest that pins every model repository revision and file digest. Upstream clients may use content-addressed caches, but a model name or branch alone is not an immutable Qantara guarantee. For sensitive environments, pre-download a reviewed revision, record file hashes, transfer it through a trusted channel, and disable runtime egress.

## Release artifact controls

The manual release workflow runs only from an existing matching `vX.Y.Z` tag selected by an owner. It:

1. verifies tag and source version metadata
2. runs lint, compilation, and the full lightweight unit suite
3. builds wheel and sdist once
4. validates metadata and forbidden/required archive contents
5. installs each artifact into a clean virtual environment and exercises public routes/resources
6. installs the built wheel into an empty target directory, creates an SPDX JSON SBOM from that clean install, and validates that the Qantara component and its runtime dependencies are present and that no lock-only packages appear (lock files are excluded from the wheel)
7. writes SHA256 checksums and machine-readable validation evidence
8. in a separate job with no third-party installs, re-verifies checksums and generates GitHub build-provenance attestations (the only job with write/OIDC permissions)
9. attaches those exact files to a draft GitHub Release

The test/build job runs with a read-only token and no dependency cache. The Docker image is built and smoke-tested on amd64 and arm64 before the publish job runs.

The workflow does not upload to PyPI and refuses to replace artifacts when a release already exists for the tag. Maintainers review the draft before publication. See [Release process](RELEASE_PROCESS.md).

Until Qantara itself is registered on PyPI, `pip-audit --strict` cannot resolve
an advisory identity for the local `qantara` distribution. CI therefore installs
Qantara to resolve its dependency set, uninstalls only that local distribution,
and audits the third-party packages left in the environment. This is a narrow,
documented exception—not a vulnerability-ID ignore.

## Regenerating hash locks

Both runtime locks are generated from their adjacent `.in` files (the top-level pins live in `ops/docker/requirements.in`) with one command, which needs [uv](https://docs.astral.sh/uv/):

```bash
python scripts/lock_requirements.py            # keep current pins, refresh hashes
python scripts/lock_requirements.py --upgrade  # re-resolve within the .in pins
python scripts/check_lock_hashes.py            # verify platform coverage
```

The script runs `uv pip compile --universal --generate-hashes --python-version 3.11 --torch-backend cpu`. Only the PyTorch ecosystem resolves from the PyTorch CPU index; every other package resolves from PyPI, so uv records the hash of every published wheel rather than only the files a mirror happened to serve. (The earlier `--index-strategy unsafe-best-match` lock took `markupsafe` from the PyTorch mirror with two hashes and failed `--require-hashes` on linux/aarch64, Windows and CPython 3.11.) The script then adds `--extra-index-url https://download.pytorch.org/whl/cpu` so pip can find the `+cpu` torch build; this is safe because every requirement is hash-pinned and pip rejects any file whose digest is not locked, whichever index serves it.

`check_lock_hashes.py` confirms, from index metadata, that each locked requirement whose marker applies has a hash-pinned wheel for CPython 3.11 and 3.12 on manylinux x86_64, manylinux aarch64, Windows amd64 and macOS arm64 (the condition `pip install --require-hashes --only-binary=:all:` enforces), without downloading multi-GB wheels. CI runs it on every pull request. Then run tests, package checks, and the dependency audit before merging.

## Offline preparation

For an egress-restricted deployment:

1. Resolve package, container, and model artifacts on a trusted staging machine.
2. Record SHA256 digests and upstream revisions in deployment records.
3. Scan artifacts according to your organization’s policy.
4. Populate the target’s wheelhouse, container store, Hugging Face/provider caches, Piper voice directory, and Ollama model store.
5. Run Qantara with egress denied and verify startup plus one synthetic turn.

Do not copy browser profiles, `.env` files, tokens, private keys, transcripts, audio captures, or unrelated caches as part of this process.

## Maintainer safeguards outside the repository

As last verified for the `0.3.1` release, repository settings enforce safeguards
that cannot be expressed solely in source (owners re-verify them, including the
required-check list after the `0.4.0` CI changes, before tagging):

- `main` requires a pull request, an up-to-date branch, all nine CI checks, and
  resolved review conversations; linear history is required and force-pushes or
  branch deletion are blocked, including for administrators
- `v*` release-tag creation is restricted to the repository owner, and matching
  tags cannot be updated or deleted after creation
- Dependency Graph, vulnerability alerts, Dependabot security updates, secret
  scanning, push protection, and private vulnerability reporting are enabled
- release publication remains manual after review of the draft assets and
  validation evidence

The approval count is intentionally zero while no independent trusted reviewer
is designated, because GitHub does not allow a pull-request author to approve
their own change. Increase it to one when another maintainer can reliably review
release and dependency changes.

## Reporting a concern

Suspected malicious or tampered Qantara artifacts should be reported privately through [SECURITY.md](../SECURITY.md). Do not post tokens, suspicious payload contents, or private deployment details in a public issue.
