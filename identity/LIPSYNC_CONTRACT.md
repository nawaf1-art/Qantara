# Lipsync Contract

## Goal

Keep avatar rendering and voice synthesis loosely coupled through a small stable contract.

## Rule

The TTS layer must not need to know how the avatar is rendered.

The renderer must not need to know which TTS engine produced the speech.

They meet through:

- playback lifecycle events
- viseme timeline data

## Phase 1 Contract

Phase 1 should emit:

- `voice_id`
- `utterance_id`
- `sample_rate`
- `duration_ms`
- `viseme_set`
- `timeline`

Timeline entry shape:

```json
{
  "t_ms": 80,
  "viseme": "AA",
  "weight": 0.92
}
```

## Phase 1 Viseme Set

Use a compact canonical set:

- `SIL`
- `PP`
- `FF`
- `TH`
- `DD`
- `KK`
- `CH`
- `SS`
- `NN`
- `RR`
- `AA`
- `E`
- `I`
- `O`
- `U`

This is small enough for 2D avatar packs and broad enough for good mouth animation.

## Renderer Requirements

Every mouth set in an avatar pack must define shapes for the active viseme set.

If a viseme is missing, the renderer should fail validation or use a declared fallback.

## Validation Rules

- every viseme used in a timeline must exist in the selected mouth set
- timeline timestamps must be monotonic
- weights must be normalized to `0.0` to `1.0`

## Phase 1 Fallback

If the backend cannot provide viseme timing yet:

- the browser may continue using amplitude-driven mouth motion
- but the contract should still be defined now so backend-generated visemes can replace it later
