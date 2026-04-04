# Voice System

## Goal

Turn voice selection into a real backend feature instead of a frontend playback trick.

## Phase 1 Choice

Phase 1 uses a local voice registry and server-side voice selection.

The browser picks a `voice_id`.
The gateway stores it per session.
The TTS backend resolves that `voice_id` through the voice registry.

## Voice Registry Responsibilities

The voice registry defines:

- available voices
- engine type
- model path
- config path
- locale
- preview sample
- transform defaults
- allowed transforms
- commercial/license notes

## Voice Identity Model

A voice preset is not only a model path.

It should include:

- `voice_id`
- `label`
- `engine`
- `model_path`
- `config_path`
- `locale`
- `base_sample_rate`
- `preview_text`
- `preview_audio_path`
- `default_rate`
- `default_pitch`
- `default_tone`
- `allowed_transforms`

## Phase 1 Engines

Primary engine:

- Piper

Optional later engines:

- Coqui TTS
- MeloTTS
- OpenVoice-style personalization layer

Those later engines should fit behind the same registry contract.

## Personalization Scope

Phase 1 voice customization:

- preset selection
- speaking rate
- pitch offset
- tone / warmth profile

Later:

- consented voice personalization
- user-owned voice cloning workflows

## What To Avoid

- cloud-only TTS as the primary path
- voice selection only in the browser after synthesis
- hidden per-engine assumptions leaking into the client

## Immediate Reality

The current repo has only one real Piper model installed.

That means:

- the current UI can expose playback profiles
- but real multi-voice TTS needs more local models in the registry

The architecture should still be built now so the system becomes real as soon as more voices are added.
