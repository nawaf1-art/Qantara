from __future__ import annotations

import os
import time

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
