# Release Evidence

Each successful release-preparation run creates:

- `qantara-X.Y.Z-py3-none-any.whl`
- `qantara-X.Y.Z.tar.gz`
- `qantara-X.Y.Z.spdx.json`
- `release-validation.json`
- `SHA256SUMS`
- GitHub build-provenance attestations

`release-validation.json` is generated only after the named workflow checks pass. It records the selected tag/version, exact commit, UTC generation time, validation names, and hashes/sizes of the build artifacts. The schema is [release-validation.schema.json](release-validation.schema.json).

The evidence states what automation ran; it is not a certification of model quality, every optional integration, or every deployment environment. Manual validation gaps belong in the release notes.

To verify downloaded files on Linux:

```bash
sha256sum --check SHA256SUMS
gh attestation verify qantara-X.Y.Z-py3-none-any.whl --repo nawaf1-art/Qantara
```

Do not create a hand-written `status: passed` evidence file. Use the tag-only release workflow so claims correspond to an actual run.
