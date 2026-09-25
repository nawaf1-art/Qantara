# Home Assistant

**Status: the Wyoming satellite bridge was removed in `0.4.0`.** Qantara currently has no Home Assistant integration. This page explains what was removed, what to do if you used it, and which directions a future integration could take.

## What was removed

Releases `0.2.2` through `0.3.1` shipped an Experimental Wyoming-protocol "satellite" endpoint (`QANTARA_WYOMING_ENABLED`, default port `10700`). The 2026-09-24 audit found that it could not work as documented and was unsafe on a LAN:

- **It did not match Home Assistant's satellite model.** A Home Assistant satellite streams microphone audio after Home Assistant sends `run-pipeline`, and Home Assistant runs the pipeline. Qantara's bridge answered only `describe`, `audio-chunk`, and `audio-stop` and ran its own STT → backend → TTS on incoming audio, so Home Assistant could add the device but nothing ever triggered it.
- **It was an unauthenticated side door.** It drove the configured backend without `QANTARA_AUTH_TOKEN`, buffered incoming audio without a limit, ignored the declared sample width and channel count, and could hang gateway shutdown while a client was connected.

The bridge, its `QANTARA_WYOMING_*` settings, and the `wyoming` dependency were removed rather than repaired.

## If you used it

- Remove `QANTARA_WYOMING_ENABLED`, `QANTARA_WYOMING_HOST`, `QANTARA_WYOMING_PORT`, `QANTARA_WYOMING_NODE_NAME`, and `QANTARA_WYOMING_AREA` from your environment, `.env` file, or Compose overrides. The gateway ignores them; a leftover `QANTARA_WYOMING_ENABLED=true` logs a warning at startup.
- Delete the Qantara "Wyoming Protocol" device in Home Assistant (**Settings → Devices & Services**); it will no longer connect.
- Close port `10700/tcp` if you opened it in a firewall.
- The `mesh` extra now installs only `zeroconf`. Reinstall your environment if you depended on `qantara[mesh]` to pull in `wyoming`.

## What works today

Home Assistant can still call Qantara's local HTTP [Voice API](VOICE_API.md) from automations or scripts (for example with a `rest_command`), subject to the gateway's normal authentication and Host policy:

- `POST /api/v1/speak` returns WAV (or raw PCM16) audio for a text string.
- `POST /api/v1/transcribe` returns text for a WAV or PCM16 clip.
- `POST /api/v1/converse` runs a text turn through Qantara's configured backend and streams the reply as Server-Sent Events.

This is a request/response integration, not an Assist pipeline or voice satellite.

## Possible future directions (not implemented)

If a Home Assistant integration returns, the audit recommends one of these designs instead of a satellite. Neither is implemented or scheduled; see the [roadmap](../ROADMAP.md).

- **Wyoming ASR/TTS services.** Offer Qantara's local STT and TTS as Wyoming `asr` and `tts` services, which is what Home Assistant still uses Wyoming for, so an Assist pipeline can use them.
- **A conversation-API adapter.** Add a Qantara backend adapter that sends finalized voice turns to Home Assistant's conversation API, so Qantara's browser voice loop can control Home Assistant.

Home Assistant satellites have moved to the ESPHome API (for example Voice PE and linux-voice-assistant); Qantara does not plan to re-implement that satellite protocol.
