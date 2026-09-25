"""Qantara unit tests.

Both invocations work from the repository root:

    python -m unittest discover -s tests
    python -m unittest tests.test_gateway_http

Helper modules such as ``protocol_fixtures`` are imported by bare name, so
the tests directory is made importable when the suite runs as a package.
"""

import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.append(_TESTS_DIR)
