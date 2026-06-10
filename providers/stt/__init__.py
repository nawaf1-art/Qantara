# Only the dependency-free base contract is re-exported here. Concrete
# providers import heavy optional dependencies, so they are imported lazily
# by providers/factory.py — never at package import time.
from providers.stt.base import STTProvider

__all__ = ["STTProvider"]
