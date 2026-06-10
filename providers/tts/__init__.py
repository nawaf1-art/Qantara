# Only the dependency-free base contract is re-exported here. Concrete
# providers (Kokoro, Piper, Chatterbox) import heavy optional dependencies,
# so they are imported lazily by providers/factory.py — never at package
# import time. Import them from their own modules if you need them directly.
from providers.tts.base import TTSProvider, VoiceSpec

__all__ = ["TTSProvider", "VoiceSpec"]
