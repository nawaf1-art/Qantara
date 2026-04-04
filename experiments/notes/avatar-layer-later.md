# Avatar Layer Later

Qantara should not treat avatar rendering as part of the core voice gateway.

## Why

The current Qantara objective is the live voice path:
- browser transport
- microphone capture
- VAD and endpointing
- STT
- TTS
- playback
- interruption
- session lifecycle
- backend adapter boundaries

That layer should stay focused on reliable spoken interaction.

Avatar presentation is a separate concern. It sits above the gateway and consumes the gateway's outputs.

## What Pika Teaches Us

The `pikastream-video-meeting` skill from `Pika-Skills` is useful as a reference for presentation and session orchestration, not for Qantara's core transport design.

Useful patterns:
- avatar identity is configured separately from the agent runtime
- voice identity is configured separately from the agent runtime
- a session is prepared before live participation begins
- live participation exposes explicit status such as join, active, and leave
- the speaking layer is driven by concise prepared context, not raw long history

## What Qantara Should Copy Later

Qantara should eventually support an avatar renderer as a separate output adapter.

That future avatar layer should consume:
- final TTS audio
- timing events for playback start and stop
- assistant text deltas or final captions
- turn state events such as active, idle, cancel, and interrupt
- persona configuration such as avatar asset, name, voice, and style

## What Must Stay Outside The Gateway

The gateway should not directly own:
- talking-head generation
- lip-sync rendering
- avatar image pipelines
- cloned voice asset management
- meeting platform-specific bot presence

Those belong to a presentation or meeting-participation layer above Qantara.

## Clean Future Boundary

Recommended layering:

1. Qantara gateway
   - receives live user audio
   - produces transcript, turn events, and reply audio

2. Avatar renderer
   - receives reply audio and timing events
   - animates a chosen avatar
   - exposes optional captions and expression hooks

3. Meeting or UI adapter
   - places that avatar/audio stream into browser UI, kiosk UI, or a future meeting platform

## Implication For Alpha

Do not mix avatar generation into the current transport spike.

Finish the reliable voice gateway first.

When the transport and interruption model are stable, add a thin avatar-output adapter on top of the existing event and audio stream model.
