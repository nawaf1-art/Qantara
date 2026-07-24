"""Single source for the runtime package version."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def read_version() -> str:
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        try:
            return version("qantara")
        except PackageNotFoundError:
            return "0.0.0"


__version__ = read_version()
