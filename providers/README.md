# Providers

Qantara uses a provider plugin system for speech-to-text and text-to-speech.

## Selection

- `QANTARA_STT_PROVIDER=faster_whisper`
- `QANTARA_TTS_PROVIDER=piper`

These are the current defaults.

## Layout

```text
providers/
├── factory.py
├── stt/
│   ├── base.py
│   └── faster_whisper.py
└── tts/
    ├── base.py
    └── piper.py
```

## How To Add An STT Provider

1. Copy `providers/stt/faster_whisper.py`.
2. Subclass `providers/stt/base.py:STTProvider`.
3. Implement:
   - `available`
   - `transcribe(samples, sample_rate) -> str`
4. Register the provider in `providers/factory.py`.
5. Document the env var name and local setup requirements.

## How To Add A TTS Provider

1. Copy `providers/tts/piper.py`.
2. Subclass `providers/tts/base.py:TTSProvider`.
3. Implement:
   - `available`
   - `default_voice_id`
   - `list_available_voices()`
   - `resolve_voice(voice_id)`
   - `synthesize(text, voice_id=None, speech_rate=None)`
4. Register the provider in `providers/factory.py`.
5. Keep it local-first. Do not add a cloud-only dependency.

## Notes

- Providers should be single-file integrations where practical.
- Provider-specific configuration should use `QANTARA_` environment variables.
- Keep gateway behavior stable when swapping providers. The provider layer should adapt to the gateway contract, not force the gateway to change.
