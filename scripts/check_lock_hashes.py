#!/usr/bin/env python3
"""Verify that Qantara's hash locks install on every supported platform.

``pip install --require-hashes --only-binary=:all: --no-deps -r LOCK`` succeeds
on a target only when, for every requirement whose environment marker applies
to that target, the lock pins the SHA-256 of at least one wheel whose tags the
target interpreter accepts. This script checks exactly that condition from
package-index metadata (PyPI's JSON simple API and the PyTorch CPU index), so
it covers every target in seconds without downloading multi-gigabyte wheels.

Targets: CPython 3.11 and 3.12 on manylinux x86_64, manylinux aarch64 (Docker
on Apple Silicon), Windows amd64 and macOS arm64.

Usage:
    python scripts/check_lock_hashes.py                 # both repository locks
    python scripts/check_lock_hashes.py path/to/lock.txt
    python scripts/check_lock_hashes.py --targets linux_aarch64
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

try:
    from packaging.markers import Marker
    from packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
    from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
except ImportError:  # pragma: no cover - CI runners always have pip's vendored copy
    from pip._vendor.packaging.markers import Marker
    from pip._vendor.packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
    from pip._vendor.packaging.utils import (
        InvalidWheelFilename,
        canonicalize_name,
        parse_wheel_filename,
    )

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCKS = (
    ROOT / "ops" / "docker" / "requirements.txt",
    ROOT / "gateway" / "transport_spike" / "requirements.txt",
)
PYPI_SIMPLE = "https://pypi.org/simple/{name}/"
PYTORCH_SIMPLE = "https://download.pytorch.org/whl/cpu/{name}/"
PYTHON_VERSIONS = ((3, 11), (3, 12))
# Pure-Python projects that publish only an sdist. pip builds these locally;
# the lock still pins the sdist hash, so --require-hashes stays enforced.
SDIST_ONLY_ALLOWED = frozenset({"docopt"})
REQUIREMENT_LINE = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)\s*(?:;\s*([^\\]+?))?\s*\\?$")
HASH_PATTERN = re.compile(r"--hash=sha256:([0-9a-f]{64})")
# glibc 2.17 (manylinux2014) through 2.39 (Ubuntu 24.04); Debian-based
# python:3.12-slim images are newer than the floor torch needs (2.28).
_GLIBC_MINORS = range(39, 16, -1)


def _linux_platforms(arch: str) -> list[str]:
    platforms = [f"manylinux_2_{minor}_{arch}" for minor in _GLIBC_MINORS]
    platforms.append(f"manylinux2014_{arch}")
    if arch == "x86_64":
        platforms += [f"manylinux_2_{minor}_{arch}" for minor in (12, 5)]
        platforms += [f"manylinux2010_{arch}", f"manylinux1_{arch}"]
    return platforms


TARGETS: dict[str, dict[str, object]] = {
    "linux_x86_64": {
        "platforms": _linux_platforms("x86_64"),
        "sys_platform": "linux",
        "platform_system": "Linux",
        "platform_machine": "x86_64",
        "os_name": "posix",
    },
    "linux_aarch64": {
        "platforms": _linux_platforms("aarch64"),
        "sys_platform": "linux",
        "platform_system": "Linux",
        "platform_machine": "aarch64",
        "os_name": "posix",
    },
    "win_amd64": {
        "platforms": ["win_amd64"],
        "sys_platform": "win32",
        "platform_system": "Windows",
        "platform_machine": "AMD64",
        "os_name": "nt",
    },
    "macos_arm64": {
        "platforms": list(mac_platforms((14, 0), "arm64")),
        "sys_platform": "darwin",
        "platform_system": "Darwin",
        "platform_machine": "arm64",
        "os_name": "posix",
    },
}


@dataclass
class LockEntry:
    name: str
    version: str
    marker: str
    hashes: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class IndexFile:
    filename: str
    sha256: str


def parse_lock(text: str) -> list[LockEntry]:
    entries: list[LockEntry] = []
    current: LockEntry | None = None
    for raw_line in text.replace("\r", "").splitlines():
        line = raw_line.strip()
        match = REQUIREMENT_LINE.match(line)
        if match:
            current = LockEntry(
                name=canonicalize_name(match.group(1)),
                version=match.group(2),
                marker=(match.group(3) or "").strip(),
            )
            entries.append(current)
            current.hashes.update(HASH_PATTERN.findall(line))
            continue
        if current is not None and line.startswith("--hash="):
            current.hashes.update(HASH_PATTERN.findall(line))
        elif not line.startswith("#"):
            current = None
    return entries


def marker_environment(python: tuple[int, int], target: str) -> dict[str, str]:
    spec = TARGETS[target]
    version = f"{python[0]}.{python[1]}"
    return {
        "implementation_name": "cpython",
        "implementation_version": f"{version}.0",
        "os_name": str(spec["os_name"]),
        "platform_machine": str(spec["platform_machine"]),
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": str(spec["platform_system"]),
        "platform_version": "",
        "python_full_version": f"{version}.0",
        "python_version": version,
        "sys_platform": str(spec["sys_platform"]),
        "extra": "",
    }


def supported_tags(python: tuple[int, int], target: str) -> set[Tag]:
    platforms = list(TARGETS[target]["platforms"])  # type: ignore[arg-type]
    interpreter = f"cp{python[0]}{python[1]}"
    tags = set(cpython_tags(python, abis=[interpreter, "abi3", "none"], platforms=platforms))
    tags.update(compatible_tags(python, interpreter=interpreter, platforms=platforms))
    return tags


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.files: list[IndexFile] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        path, _, fragment = href.partition("#sha256=")
        if fragment:
            self.files.append(IndexFile(unquote(path.rsplit("/", 1)[-1]), fragment.strip()))


def _fetch(url: str, *, json_api: bool) -> bytes:
    headers = {"User-Agent": "qantara-lock-check"}
    if json_api:
        headers["Accept"] = "application/vnd.pypi.simple.v1+json"
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last_error}")


def index_files(name: str) -> list[IndexFile]:
    files: list[IndexFile] = []
    payload = json.loads(_fetch(PYPI_SIMPLE.format(name=name), json_api=True))
    for item in payload.get("files", []):
        digest = (item.get("hashes") or {}).get("sha256")
        if digest:
            files.append(IndexFile(item["filename"], digest))
    if name == "torch":
        parser = _AnchorParser()
        parser.feed(_fetch(PYTORCH_SIMPLE.format(name=name), json_api=False).decode("utf-8"))
        files.extend(parser.files)
    return files


def _file_version(filename: str) -> str | None:
    try:
        return str(parse_wheel_filename(filename)[1])
    except InvalidWheelFilename:
        return None


def check_entry(
    entry: LockEntry,
    files: list[IndexFile],
    python: tuple[int, int],
    target: str,
    tags: set[Tag],
) -> str | None:
    """Return None when installable, else a short reason."""
    locked = [item for item in files if item.sha256 in entry.hashes]
    for item in locked:
        if not item.filename.endswith(".whl"):
            continue
        try:
            _, _, _, wheel_tags = parse_wheel_filename(item.filename)
        except InvalidWheelFilename:
            continue
        if wheel_tags & tags:
            return None
    if any(item.filename.endswith((".tar.gz", ".zip")) for item in locked):
        if entry.name in SDIST_ONLY_ALLOWED:
            return None
        return "only an sdist hash is locked"
    if not locked:
        return f"none of {len(entry.hashes)} locked hashes match an index file"
    return f"no locked wheel for cp{python[0]}{python[1]} {target} ({len(entry.hashes)} hashes)"


def check_locks(locks: list[Path], targets: list[str]) -> list[str]:
    parsed = {lock: parse_lock(lock.read_text(encoding="utf-8")) for lock in locks}
    names = sorted({entry.name for entries in parsed.values() for entry in entries})
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        listings = dict(zip(names, pool.map(index_files, names), strict=True))

    errors: list[str] = []
    for lock, entries in parsed.items():
        label = lock.relative_to(ROOT) if lock.is_relative_to(ROOT) else lock
        for python in PYTHON_VERSIONS:
            for target in targets:
                env = marker_environment(python, target)
                tags = supported_tags(python, target)
                applicable = [
                    entry for entry in entries if not entry.marker or Marker(entry.marker).evaluate(env)
                ]
                failures = []
                for entry in applicable:
                    reason = check_entry(entry, listings[entry.name], python, target, tags)
                    if reason is not None:
                        failures.append(f"{entry.name}=={entry.version}: {reason}")
                status = "ok" if not failures else f"FAIL ({len(failures)})"
                print(f"{label} cp{python[0]}{python[1]} {target:14s} {len(applicable):4d} packages {status}")
                errors.extend(f"{label} cp{python[0]}{python[1]} {target}: {failure}" for failure in failures)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("locks", nargs="*", type=Path, help="lock files (default: both repository locks)")
    parser.add_argument("--targets", nargs="+", choices=sorted(TARGETS), default=list(TARGETS))
    args = parser.parse_args()
    locks = [path.resolve() for path in (args.locks or DEFAULT_LOCKS)]
    try:
        errors = check_locks(locks, args.targets)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"lock hash check failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("lock hash check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print("every locked requirement has a hash-pinned wheel for each target")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
