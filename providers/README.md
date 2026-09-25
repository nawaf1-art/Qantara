# Providers

Qantara uses explicit provider boundaries for speech-to-text and text-to-speech. Provider selection changes speech implementation without changing the gateway/adapter contract.

## Defaults and selections

- Default STT: `faster_whisper`
- Default TTS: `auto`

Supported selectors:

```text
QANTARA_STT_PROVIDER=faster_whisper
QANTARA_TTS_PROVIDER=auto        # default
QANTARA_TTS_PROVIDER=routed
QANTARA_TTS_PROVIDER=piper
QANTARA_TTS_PROVIDER=kokoro
QANTARA_TTS_PROVIDER=chatterbox
```

`auto` picks at startup: when Kokoro is importable and a Piper voice is usable it builds the language router (`routing.py`) with Kokoro first and Piper second, so Kokoro speaks English, Spanish, and French and Piper speaks Arabic and anything Kokoro lacks; with only one of them it uses that one. `routed` always builds the router. Docker Compose sets `kokoro` because the image has no Piper.

Every path refuses a voice whose locale does not match the text's script: synthesis raises `NoVoiceForLanguage` (`no_voice_for_language`), and the browser shows a plain message instead of, for example, reading Arabic with an English voice. Japanese is listed in the language catalog but reports `tts_available: false` because no installed voice speaks it.

`faster_whisper`, Piper, and Kokoro are Beta surfaces; Chatterbox is Experimental. See [`docs/FEATURES.md`](../docs/FEATURES.md).

## Installation boundary

- `.[speech]` installs faster-whisper, Kokoro, NumPy, and SoundFile. Kokoro only installs on Python 3.11/3.12; on 3.13+ the extra installs STT only.
- Kokoro needs the spaCy `en_core_web_sm` model (`python -m spacy download en_core_web_sm`). With `QANTARA_OFFLINE=1` or `HF_HUB_OFFLINE=1` a missing model fails clearly instead of triggering a download.
- Piper remains operator-supplied: install `piper-tts` and fetch voices with `scripts/fetch_piper_voices.sh` (pinned revision, SHA-256 verified). When `piper-tts` is importable Piper runs in-process (`QANTARA_PIPER_IN_PROCESS=1`, default); `QANTARA_PIPER_MODEL` selects an explicit model file.
- `.[chatterbox]` installs the separate resource-heavy Chatterbox runtime.
- First use can download model assets according to the selected provider.

See [`docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md`](../docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md) and [`docs/CONFIGURATION.md`](../docs/CONFIGURATION.md).

## Layout

```text
providers/
├── factory.py
├── text_script.py
├── voice_registry.py
├── stt/
│   ├── base.py
│   └── faster_whisper.py
└── tts/
    ├── base.py
    ├── chatterbox.py
    ├── chatterbox_runtime.py
    ├── kokoro.py
    ├── piper.py
    └── routing.py
```

## faster-whisper notes

- The gateway hands STT the whole utterance, up to `QANTARA_MAX_UTTERANCE_MS` (30 s by default) with 400 ms of pre-roll.
- `QANTARA_STT_LANGUAGES` (for example `en,ar`) restricts language detection; `fa`, `ur`, and `ps` detections fold into `ar`. In directional and live translation modes the declared source language is forced.
- `QANTARA_WHISPER_BEAM_SIZE` defaults to `1` on CPU and `5` on CUDA.
- A hallucination filter drops segments Whisper marks as probably not speech while unsure of the words, highly repetitive text, and known silence/noise phrases.
- The gateway resolves Arabic/English code-switching from the share of Arabic versus Latin letters (digits and punctuation ignored); a confident detection (probability ≥ 0.6 over ≥ 1.5 s of speech) wins.

## Adding an STT provider

1. Implement `providers/stt/base.py:STTProvider`.
2. Provide `available` and `transcribe(samples, sample_rate) -> STTResult`.
3. Register the selector in `providers/factory.py`.
4. Add availability, transcription, concurrency, and cleanup tests.
5. Document dependencies, model downloads, variables, languages, and status.

## Adding a TTS provider

1. Implement `providers/tts/base.py:TTSProvider`.
2. Provide availability, voice listing/resolution, and synthesis.
3. Return valid PCM samples plus the resolved `VoiceSpec`.
4. Register the selector in `providers/factory.py`.
5. Add voice, sample-rate, bounds, timeout, and cleanup tests.
6. Document dependencies, assets, variables, limitations, and status.

## Kokoro notes

- `QANTARA_KOKORO_VOICE` overrides the default voice id (`af_heart`). Spanish (`ef_dora`) and French (`ff_siwis`) voices are registered for routing.
- `QANTARA_KOKORO_REPO_ID` overrides the model repository.
- `QANTARA_KOKORO_DEVICE` selects the device.
- Kokoro emits 24 kHz audio; the gateway preserves the provider sample rate.
- Cold-start downloads and `espeak-ng` availability can affect startup and pronunciation.

Providers must remain local-capable by default. A cloud-only speech dependency is not acceptable as the required path.
