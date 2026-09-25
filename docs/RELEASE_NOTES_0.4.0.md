# Qantara 0.4.0 Release Notes

> [!NOTE]
> `0.4.0` is the current source version. It is not yet tagged or published; the `v0.4.0` GitHub Release and its evidence are created by the owner-controlled [release process](RELEASE_PROCESS.md). Until then the latest published release is `v0.3.1`. Qantara is not published to PyPI.

Qantara `0.4.0` fixes the problems found by the 2026-09-24 platform audit. The core voice path now does what the documentation says: long questions are transcribed whole, backend failures are visible instead of silent, long answers are no longer cut off at 30 seconds, interruptions produce one clean result, and Arabic replies are spoken by an Arabic voice (or reported, never misread). It also closes several LAN exposure gaps and removes the Home Assistant Wyoming bridge, which could not work. Several of these changes are breaking; read the upgrade notes.

The full list is in the [changelog](../CHANGELOG.md#040---unreleased).

## Highlights

- **Whole-utterance speech recognition.** The gateway buffers each utterance from speech onset (with 400 ms of pre-roll, up to 30 s) instead of transcribing the last 6 s of microphone audio. Optional `QANTARA_STT_LANGUAGES` restricts detection, a hallucination filter drops silence artefacts, and translation modes use the declared source language.
- **Language-routed speech output.** The new default `QANTARA_TTS_PROVIDER=auto` sends English, Spanish, and French to Kokoro and Arabic to Piper when both are installed. Text that no installed voice can speak is reported as `no_voice_for_language` instead of being read by a voice for another script. Piper runs in-process, and `scripts/fetch_piper_voices.sh` fetches checksum-verified voices.
- **Visible, patient backends.** Adapter exceptions reach the browser as `turn_failed` with `failure_kind` and `retriable`. Session-backend streams use a 90 s idle timeout with bridge keep-alives instead of a 30 s total limit. The OpenAI-compatible adapter strips inline `<think>` reasoning, keeps one system message, trims history in whole exchanges, and retries once after a context-length error.
- **Clean interruptions.** Each turn owns its cancellation: one `turn_interrupted`, then at most one `cancel_status`, and no assistant text after the interrupt. A barge-in no longer blocks the WebSocket receive loop.
- **Fail-closed LAN policy.** Without `QANTARA_AUTH_TOKEN` the gateway answers only loopback `Host` values (or `QANTARA_ALLOWED_HOSTS`). Browser logins are per-login server-side sessions, failed credentials are rate-limited, cross-site `/api/*` requests are refused, and the SSRF allowlist is explicit.
- **Safer, working mesh (still Experimental).** LAN binds require a 24+ character token, the election uses the receiver's clock and deterministic tie-breaks, unreachable peers cannot stall the voice loop, and loopback nodes no longer advertise themselves. It has not yet been validated across physical devices.
- **Easier installs.** `qantara`, `qantara doctor`, and `qantara-doctor` console scripts; clear Python 3.12 and CPU-only PyTorch guidance; hash locks that work on arm64, Windows, and Python 3.11; a Docker model-cache volume; and CI on Python 3.11–3.14 with Docker and extras-resolution checks.
- **A simpler browser client.** The voice page works behind the HTTPS proxy, opens on a conversation view that connects automatically and needs one **Start** click, explains errors in plain language, and captures audio through an AudioWorklet with anti-aliasing.
- **New Python client.** `qantara.control.VoiceControl` drives a connected browser session from Python (`status`, `speak`, `interrupt`).

## Upgrade notes

These are breaking or behavior-changing:

1. **LAN access requires a token.** Set `QANTARA_AUTH_TOKEN` (24+ characters, no whitespace) before using Qantara from another device, through the Caddy setup (`Host: qantara.local`), or through Docker by LAN IP. Without it those requests get HTTP 421 `lan_access_requires_token`. `QANTARA_ALLOWED_HOSTS` is the unauthenticated alternative for fully trusted networks. `http://localhost:8765` is unaffected.
2. **The Wyoming / Home Assistant bridge was removed.** Remove `QANTARA_WYOMING_*` settings, delete the Qantara Wyoming device in Home Assistant, and close port 10700. The `mesh` extra no longer installs `wyoming`. See [Home Assistant](HOMEASSISTANT.md) for alternatives.
3. **Mesh LAN nodes need `QANTARA_MESH_TOKEN`.** A non-loopback mesh bind refuses to start without a 24+ character token (or `QANTARA_MESH_ALLOW_INSECURE=1`); invalid roles or node ids abort startup. Upgrade every mesh node together.
4. **CLI flags now override environment variables** (`explicit CLI flags > environment variables > selected YAML file > built-in defaults`). A missing `--config` / `QANTARA_CONFIG` file stops startup with exit code 2.
5. **Voice API PCM content type changed** to `audio/pcm;rate=N;channels=1;encoding=signed-int;bits=16;endian=little` (bytes unchanged), and `X-Sample-Rate` is a plain integer. `/speak` text is limited to 4000 characters by default.
6. **`turn_interrupted` no longer has a `resumable` field.** It was always `true`.
7. **Kokoro requires Python 3.11 or 3.12.** On Python 3.13+ `.[speech]` installs STT only. Create native venvs with `python3.12 -m venv`, and run `python -m spacy download en_core_web_sm` for Kokoro.
8. **The default TTS provider is `auto`.** Set `QANTARA_TTS_PROVIDER=piper` to keep the previous default. The Docker image ships Kokoro only, so it does not speak Arabic.
9. **Custom session backends** that stay silent for more than 90 s must send keep-alive events or raise `QANTARA_BACKEND_IDLE_TIMEOUT`.
10. Browser sign-ins do not survive a gateway restart.

## Known gaps

- Mesh frame replay protection is not implemented ([#26](https://github.com/nawaf1-art/Qantara/issues/26)), and the mesh has not been validated across physical devices.
- Arabic speech output needs a native install with `piper-tts` and the Arabic Piper voice; the Docker image does not include Piper.
- There is no Home Assistant integration in this release.
- Browser behavior (AudioWorklet capture, echo cancellation, barge-in in speaker mode) is covered by unit tests of the gateway side and by review of the client code; a recorded real-device session (phone plus laptop, Arabic and English, interruptions) has not yet been published for this version.
- No new benchmark numbers are published for `0.4.0`; [Benchmarks](BENCHMARKS.md) remain historical.

## Compatibility

The WebSocket PCM transport, the adapter interface (`adapters/base.py`), and the `qantara.VoiceGateway` API are unchanged apart from the items above. Agent protocol v1 keeps its version; the removal of the always-true `turn_interrupted.resumable` field is the one field removal. No namespace migration is included.

## Validation evidence

Once published, the GitHub Release is the canonical evidence bundle for this version. It attaches the wheel and source archive built by the tag-only workflow together with `SHA256SUMS`, an SPDX SBOM generated from a clean install of the wheel, and `release-validation.json`; GitHub also records provenance attestations for those artifacts. Verify downloads against the attached checksums and confirm that the release tag resolves to the commit recorded in the validation file.
