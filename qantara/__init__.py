"""Qantara Python SDK.

Embed the local-first voice gateway in your own Python program:

    from qantara import VoiceGateway

    gateway = VoiceGateway(host="127.0.0.1", port=8765)
    gateway.run()

Open http://127.0.0.1:8765 and start talking. See protocols/agent.md for
the event contract and docs/CONFIGURATION.md for the QANTARA_* environment
variables that select backends, STT/TTS providers, and security options.
"""

from qantara.version import __version__
from qantara.voice_gateway import VoiceGateway

__all__ = ["VoiceGateway", "__version__"]
