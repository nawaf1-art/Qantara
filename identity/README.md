# Identity Layer

This directory defines Qantara's owned identity stack for:

- avatar packs
- avatar descriptors
- voice registry
- lipsync / viseme contracts

It is intentionally separate from the voice gateway runtime.

## Phase 1 Direction

Phase 1 is:

- 2D, parts-based, browser-rendered avatars
- descriptor-driven customization
- real backend voice selection through a voice registry
- a stable lipsync contract between TTS and renderer

Phase 1 is not:

- proprietary avatar SDKs
- cloud-only voice systems
- 3D-first avatar authoring
- freeform illustration tools

## Files

- [`AVATAR_SYSTEM.md`](/home/nawaf/Projects/Qantara/identity/AVATAR_SYSTEM.md)
- [`VOICE_SYSTEM.md`](/home/nawaf/Projects/Qantara/identity/VOICE_SYSTEM.md)
- [`LIPSYNC_CONTRACT.md`](/home/nawaf/Projects/Qantara/identity/LIPSYNC_CONTRACT.md)
- [`avatar-descriptor.schema.json`](/home/nawaf/Projects/Qantara/identity/avatar-descriptor.schema.json)
- [`voice-registry.schema.json`](/home/nawaf/Projects/Qantara/identity/voice-registry.schema.json)

## Future Direction

3D/VRM support is a later renderer option, not the Phase 1 foundation.
