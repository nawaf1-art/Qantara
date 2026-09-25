"""Source-checkout shim for the Qantara environment check.

The implementation lives in ``qantara/doctor.py`` (installed as
``qantara doctor`` and ``qantara-doctor``).

Run: python scripts/doctor.py [--mesh]   (or: make doctor ARGS=--mesh)
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from qantara.doctor import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
