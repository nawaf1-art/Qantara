"""Qantara Python SDK.

Embed the local-first voice gateway in your own Python program:

    from qantara import VoiceGateway

    gateway = VoiceGateway(host="127.0.0.1", port=8765)
    gateway.run()

Open http://127.0.0.1:8765 and start talking. See protocols/agent.md for
the event contract and docs/CONFIGURATION.md for the QANTARA_* environment
variables that select backends, STT/TTS providers, and security options.
"""

from __future__ import annotations

import os

from qantara.voice_gateway import VoiceGateway


def _read_version() -> str:
    version_file = os.path.join(os.path.dirname(__file__), "..", "VERSION")
    try:
        with open(version_file, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        try:
            from importlib.metadata import version

            return version("qantara")
        except Exception:
            return "0.0.0"


__version__ = _read_version()

__all__ = ["VoiceGateway", "__version__"]
