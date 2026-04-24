# Voice Registry

This directory will hold owned local voice definitions for Qantara.

Phase 1 direction:

- registry-driven real `voice_id` selection
- Piper as the first engine
- more engines can be added later behind the same contract

Expected future structure:

```text
voice-registry/
  voices.json
  previews/
  models/
```

The browser may expose many presentation profiles, but only registry-backed
`voice_id` values count as real backend voices.
