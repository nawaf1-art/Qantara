# Release Checklist

Use this checklist together with [RELEASE_PROCESS.md](RELEASE_PROCESS.md). It is intentionally version-neutral.

## Source preparation

- [ ] Version matches in `VERSION`, `pyproject.toml`, changelog, README, and roadmap.
- [ ] Changelog entry is complete and upgrade notes identify compatibility/security changes.
- [ ] Public docs and feature statuses describe implemented behavior only.
- [ ] Dependency/lock changes were reviewed and audited.
- [ ] No secrets, certificates, logs, model weights, audio, private notes, or caches are tracked or packaged.

## Pull request validation

- [ ] Required CI jobs pass on the exact release commit.
- [ ] Wheel and sdist pass metadata/content checks and clean-install smoke tests.
- [ ] Docker configuration is valid; a clean build/health check was run when Docker changed.
- [ ] Relevant real backend/browser/device checks and gaps are recorded.
- [ ] Security/privacy and rollback implications were reviewed.

## Owner-controlled release

- [ ] Release PR is merged without rewriting published history.
- [ ] Owner creates the exact protected `vX.Y.Z` tag on the intended commit.
- [ ] Manual release workflow is dispatched from that tag with matching `X.Y.Z` input.
- [ ] Draft assets include wheel, sdist, checksums, SPDX SBOM, validation evidence, and provenance.
- [ ] Checksums and validation commit/tag are reviewed independently.
- [ ] Draft notes contain upgrade/security guidance and no unsupported claims.
- [ ] GitHub Release is published manually; PyPI remains a separate explicit decision.

## After publication

- [ ] Fresh install from the published artifact succeeds.
- [ ] Release links and documentation resolve.
- [ ] Version/tag/release are recorded in the project’s normal public channels.
- [ ] Any correction uses a new version; published artifacts are not silently replaced.
