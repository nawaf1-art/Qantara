"""Source-checkout shim for the Qantara launcher.

The implementation lives in ``qantara/cli.py`` and is installed as the
``qantara`` console script. ``python cli.py ...`` keeps working from a clone.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from qantara.cli import (  # noqa: E402,F401
    MANAGED_BRIDGE_PORT,
    _apply_config_defaults,
    _apply_env,
    _classify_backend,
    build_parser,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
