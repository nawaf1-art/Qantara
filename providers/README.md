# Providers

Qantara uses explicit provider boundaries for speech-to-text and text-to-speech. Provider selection changes speech implementation without changing the gateway/adapter contract.

## Defaults and selections

- Default STT: `faster_whisper`
- Default TTS: `piper`

Supported selectors:

```text
QANTARA_STT_PROVIDER=faster_whisper
QANTARA_TTS_PROVIDER=piper
QANTARA_TTS_PROVIDER=kokoro
QANTARA_TTS_PROVIDER=chatterbox
```

`faster_whisper`, Piper, and Kokoro are Beta surfaces; Chatterbox is Experimental. See [`docs/FEATURES.md`](../docs/FEATURES.md).

## Installation boundary

- `.[speech]` installs faster-whisper, Kokoro, NumPy, and SoundFile.
- Piper remains operator-supplied: its Python module/executable and voice files are not installed by the `speech` extra.
- `.[chatterbox]` installs the separate resource-heavy Chatterbox runtime.
- First use can download model assets according to the selected provider.

See [`docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md`](../docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md) and [`docs/CONFIGURATION.md`](../docs/CONFIGURATION.md).

## Layout

```text
providers/
├── factory.py
├── stt/
│   ├── base.py
│   └── faster_whisper.py
└── tts/
    ├── base.py
    ├── chatterbox.py
    ├── kokoro.py
    └── piper.py
```

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

- `QANTARA_KOKORO_VOICE` overrides the voice id.
- `QANTARA_KOKORO_REPO_ID` overrides the model repository.
- `QANTARA_KOKORO_DEVICE` selects the device.
- Kokoro emits 24 kHz audio; the gateway preserves the provider sample rate.
- Cold-start downloads and `espeak-ng` availability can affect startup and pronunciation.

Providers must remain local-capable by default. A cloud-only speech dependency is not acceptable as the required path.
