# Governance

Qantara is a maintainer-led open-source project. The repository owner and maintainers are accountable for technical direction, security response, merges, tags, and releases.

## How decisions are made

- Small fixes and documentation changes are decided through pull-request review.
- New features should begin with an issue that states the user problem, local-first behavior, maintenance cost, and compatibility impact.
- Changes to locked architecture decisions require an issue and a written architecture decision before implementation.
- Security-sensitive details are handled privately until coordinated disclosure is appropriate.
- Maintainers may decline work that adds an unsupported public-internet posture, a required cloud dependency, hidden complexity, or ongoing maintenance the project cannot sustain.

Consensus is preferred. When consensus is not available, the repository owner makes the final decision and records the reasoning in the issue, PR, or an ADR.

## Roles

### Contributors

Anyone who submits issues, documentation, tests, code, reviews, or reproducible validation evidence. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).

### Maintainers

Trusted contributors with repository review/merge responsibility. Maintainer access is granted by the repository owner based on sustained, constructive work, security judgment, and demonstrated understanding of Qantara’s architecture.

### Release owners

Maintainers authorized to create protected version tags and publish reviewed draft releases. Release ownership should remain narrow because tags and artifacts are long-lived trust anchors.

## Releases

Releases follow [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md). Source automation can prepare evidence and a draft release, but a human release owner verifies the tag, checks, changelog, artifacts, checksums, SBOM, and provenance before publication.

The project does not rewrite or replace published release artifacts. A correction uses a new version, with a clear changelog and advisory when necessary.

## Changes to governance

Governance changes use a normal pull request and should explain why the current process is insufficient. Material changes should remain open long enough for active contributors to comment.
