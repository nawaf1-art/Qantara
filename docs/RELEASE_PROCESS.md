# Release Process

Qantara releases are owner-controlled. Automation validates and prepares a draft; it does not decide to create a tag, publish a GitHub Release, upload to PyPI, or merge code.

## Preconditions

- The release candidate is reviewed through a pull request against `main`.
- Required checks pass on the intended commit.
- Version metadata and changelog are final.
- The repository owner has enabled branch protection for `main` and restricted creation/deletion of `v*` tags.

Rulesets are repository settings, not source files. Owners must verify them in GitHub before each release cycle.

## Prepare the release pull request

1. Set the next version in `VERSION` and `pyproject.toml`.
2. Add the first changelog heading as `## [X.Y.Z] - Unreleased` during review.
3. Update README/roadmap source-version markers and any versioned install examples.
4. Run the commands in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
5. Merge only after CI passes and the public diff is reviewed.

`scripts/check_release_consistency.py --expected X.Y.Z` prevents common metadata drift.
`scripts/check_tracked_artifacts.py` rejects tracked credentials, certificates,
model weights, audio captures, logs, caches, and unexpectedly large files.

## Create the tag

A release owner creates `vX.Y.Z` on the reviewed commit. Prefer a signed annotated tag when the owner’s signing setup is established:

```bash
git switch main
git pull --ff-only
git tag -s vX.Y.Z -m "Qantara vX.Y.Z"
git push origin vX.Y.Z
```

If signed tags are not yet available, use an annotated tag and record that limitation. Never move, delete/recreate, or force-update a published version tag. A mistake requires a new version.

## Prepare the draft release

In GitHub Actions, select **Prepare draft release**, choose the existing `vX.Y.Z` ref, and enter `X.Y.Z`. The workflow fails if the selected ref and input differ.

The workflow builds once and uses those exact artifacts for checks, clean installs, checksums, SBOM, validation evidence, provenance, and draft-release attachment. It refuses to overwrite an existing release for the tag.

Review the draft:

- tag and commit are exact
- wheel/sdist names and versions are correct
- `SHA256SUMS` matches downloaded assets
- `release-validation.json` reports the expected commit and checks
- SPDX SBOM and provenance links are present
- notes accurately separate changes, upgrade requirements, security fixes, and known gaps

Only a release owner publishes the draft.

## PyPI policy

The current workflow does not publish to PyPI. Adding PyPI requires a separate reviewed change with trusted publishing, a protected environment, package-name ownership verification, and a documented rollback/yank process. Never upload manually from an unverified local `dist/` directory.

## Failure and rollback

- Before publication: delete the draft if necessary, fix source through a new PR, and create a new tag/version when the original tag has been shared externally.
- After publication: do not replace assets. Publish a corrective release and advisory/changelog note.
- For a compromised credential or artifact: rotate credentials, preserve evidence privately, use the security process, and revoke/yank only through the relevant registry’s documented mechanism.

Release evidence format is documented in [releases/README.md](releases/README.md).
