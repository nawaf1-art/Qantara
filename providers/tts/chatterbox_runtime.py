from __future__ import annotations

import os


class RealChatterboxBackend:
    sample_rate: int = 24000

    def __init__(self) -> None:
        from chatterbox.tts import ChatterboxTTS  # type: ignore[import-not-found]

        device = os.environ.get("QANTARA_CHATTERBOX_DEVICE", "cpu").strip().lower() or "cpu"
        self._model = ChatterboxTTS.from_pretrained(device=device)

    def generate(
        self,
        text: str,
        *,
        exaggeration: float,
        cfg_weight: float,
        voice_prompt_path: str | None,
    ) -> list[int]:
        wav = self._model.generate(
            text,
            audio_prompt_path=voice_prompt_path,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
        )
        import numpy as np

        if hasattr(wav, "detach"):
            arr = wav.squeeze().detach().cpu().numpy()
        else:
            arr = np.asarray(wav).squeeze()
        arr = np.clip(arr, -1.0, 1.0)
        return (arr * 32767.0).astype(np.int16).tolist()


def load_backend() -> RealChatterboxBackend:
    return RealChatterboxBackend()
