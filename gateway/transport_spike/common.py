from __future__ import annotations

import os
import sys
import time
from array import array

CURRENT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
CLIENT_SPIKE_DIR = os.path.join(REPO_ROOT, "client", "transport-spike")
CLIENT_SETUP_DIR = os.path.join(REPO_ROOT, "client", "setup")
CLIENT_TRANSLATE_DIR = os.path.join(REPO_ROOT, "client", "translate")
IDENTITY_DIR = os.path.join(REPO_ROOT, "identity")

PCM_KIND = 0x01
TARGET_SAMPLE_RATE = 16000
TONE_HZ = 440.0
TONE_SECONDS = 1.25
FRAME_SAMPLES = 1920
DEFAULT_HOST = os.environ.get("QANTARA_SPIKE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("QANTARA_SPIKE_PORT", "8765"))
TLS_CERT_FILE = os.environ.get("QANTARA_TLS_CERT")
TLS_KEY_FILE = os.environ.get("QANTARA_TLS_KEY")
DEFAULT_SPEECH_RATE = float(os.environ.get("QANTARA_DEFAULT_SPEECH_RATE", "1.2"))
SESSION_STORE_TTL_MS = int(os.environ.get("QANTARA_SESSION_STORE_TTL_MS", str(30 * 60 * 1000)))
MANAGED_BRIDGE_PORT = 19120

# Mesh (0.2.2). Role-driven opt-in; default is disabled so single-node
# installs are unchanged. Reading env at start_mesh() time (not here)
# to keep unittest.mock.patch.dict working cleanly in tests.

# Wyoming satellite (0.2.2). Read at import time — tests that need
# env-sensitive Wyoming behaviour should call start_wyoming() which
# re-reads the env at call time.
WYOMING_ENABLED = os.environ.get("QANTARA_WYOMING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
WYOMING_PORT = int(os.environ.get("QANTARA_WYOMING_PORT", "10700"))
WYOMING_NODE_NAME = os.environ.get("QANTARA_WYOMING_NODE_NAME", "qantara")
WYOMING_AREA = os.environ.get("QANTARA_WYOMING_AREA", "")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


DEFAULT_MAX_UTTERANCE_MS = 30000
UTTERANCE_PREROLL_MS = 400
# A new VAD speech onset within this much audio after the previous speech
# ended continues the same utterance (the user paused mid-sentence). Past
# it, the old utterance is treated as abandoned (the client skipped the
# submit) and a fresh one starts. Comfortably above the browser client's
# 300 ms VAD hang + 1200 ms endpoint silence.
UTTERANCE_RESUME_MS = 2000


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def decode_pcm16le(payload: bytes | bytearray | memoryview) -> array:
    """Decode little-endian PCM16 bytes into an ``array('h')`` in C, with no
    per-sample Python loop."""
    samples = array("h")
    samples.frombytes(bytes(payload))
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


class UtteranceBuffer:
    """Holds the audio of the current user utterance.

    Browser clients stream the mic continuously and mark speech with
    ``vad_state`` messages. The buffer keeps a short pre-roll ring while
    idle, starts an utterance on the speech onset (seeded with the pre-roll
    so the first syllable survives VAD latency), keeps accumulating through
    short pauses and the endpoint silence, and is cleared on submit.

    Push-to-talk clients (the translate page) send only
    ``mic_stream_started``/``mic_stream_stopped``; those bound the utterance.
    A client that sends no markers at all gets a rolling window capped at
    the utterance limit (legacy behaviour).
    """

    def __init__(
        self,
        sample_rate: int = TARGET_SAMPLE_RATE,
        max_ms: int | None = None,
        preroll_ms: int = UTTERANCE_PREROLL_MS,
        resume_ms: int = UTTERANCE_RESUME_MS,
    ) -> None:
        if max_ms is None:
            max_ms = _env_positive_int("QANTARA_MAX_UTTERANCE_MS", DEFAULT_MAX_UTTERANCE_MS)
        self.sample_rate = sample_rate
        self.max_samples = max(1, sample_rate * max_ms // 1000)
        self.preroll_samples = max(0, sample_rate * preroll_ms // 1000)
        self.resume_samples = max(0, sample_rate * resume_ms // 1000)
        self._samples = array("h")
        self._preroll = array("h")
        self.markers_seen = False
        self.vad_seen = False
        self.active = False
        self.origin: str | None = None
        self.speaking = False
        self.speech_samples = 0
        self._samples_since_speech_end = 0
        self.truncated = False

    def __len__(self) -> int:
        return len(self._samples)

    @property
    def full(self) -> bool:
        return len(self._samples) >= self.max_samples

    def snapshot(self) -> array:
        """The current utterance audio (not a copy; do not mutate)."""
        return self._samples

    def replace(self, samples: list[int] | array) -> None:
        """Replace the buffered audio (used by tests and legacy callers)."""
        self._samples = array("h", samples)

    def _start(self, origin: str, *, with_preroll: bool, was_unmarked: bool = False) -> None:
        recent_in_utterance = was_unmarked or (self.active and self.origin == "stream")
        if with_preroll and recent_in_utterance and self.preroll_samples:
            # Switching from an unmarked or stream-bounded capture to VAD
            # boundaries: the recent audio lives in the utterance, not in the
            # pre-roll ring.
            self._preroll = self._samples[-self.preroll_samples:]
        self._samples = array("h", self._preroll) if with_preroll else array("h")
        self._preroll = array("h")
        self.active = True
        self.origin = origin
        self.speech_samples = 0
        self._samples_since_speech_end = 0
        self.truncated = False

    def speech_started(self) -> None:
        was_unmarked = not self.markers_seen
        self.markers_seen = True
        self.vad_seen = True
        if self.speaking and self.origin == "vad":
            return
        continue_current = (
            self.active
            and self.origin == "vad"
            and not self.full
            and self._samples_since_speech_end <= self.resume_samples
        )
        if not continue_current:
            self._start("vad", with_preroll=True, was_unmarked=was_unmarked)
        self.speaking = True
        self._samples_since_speech_end = 0

    def speech_ended(self) -> None:
        self.markers_seen = True
        self.speaking = False
        self._samples_since_speech_end = 0

    def stream_started(self) -> None:
        self.markers_seen = True
        if self.vad_seen:
            return
        self._start("stream", with_preroll=False)
        self.speaking = True

    def stream_stopped(self) -> None:
        self.markers_seen = True
        if self.vad_seen:
            return
        self.speaking = False
        self._samples_since_speech_end = 0

    def append_pcm(self, payload: bytes | bytearray | memoryview) -> None:
        self.append_samples(decode_pcm16le(payload))

    def append_samples(self, samples: array) -> None:
        count = len(samples)
        if not count:
            return
        if not self.markers_seen:
            self._samples.extend(samples)
            overflow = len(self._samples) - self.max_samples
            if overflow > 0:
                del self._samples[:overflow]
            if self.speaking:
                self.speech_samples += count
            return
        if not self.active:
            self._preroll.extend(samples)
            overflow = len(self._preroll) - self.preroll_samples
            if overflow > 0:
                del self._preroll[:overflow]
            return
        room = self.max_samples - len(self._samples)
        if room >= count:
            self._samples.extend(samples)
        else:
            if room > 0:
                self._samples.extend(samples[:room])
            self.truncated = True
        if self.speaking:
            self.speech_samples += min(count, max(room, 0))
            return
        self._samples_since_speech_end += count
        if self.origin == "vad" and self._samples_since_speech_end > self.resume_samples:
            # Past the resume window: stop growing the utterance. It stays
            # available for a (late) submit, while new audio feeds the
            # pre-roll ring for the next onset.
            self.active = False

    @property
    def speech_ms(self) -> float:
        if not self.markers_seen:
            return 1000.0 * len(self._samples) / max(self.sample_rate, 1)
        return 1000.0 * self.speech_samples / max(self.sample_rate, 1)

    def take(self) -> tuple[array, float]:
        """Return (samples, speech duration in ms) and reset for the next utterance."""
        samples = self._samples
        speech_ms = self.speech_ms
        self._samples = array("h")
        self._preroll = array("h")
        self.active = False
        self.origin = None
        self.speech_samples = 0
        self._samples_since_speech_end = 0
        self.truncated = False
        if self.speaking and self.vad_seen:
            # Speech is still in progress (a submit raced a new onset):
            # keep capturing it as a fresh utterance.
            self._start("vad", with_preroll=False)
        return samples, speech_ms
