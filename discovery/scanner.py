"""LAN-wide AI backend discovery.

Scans private IP ranges for known LLM server ports, identifies
server type via HTTP fingerprinting, and extracts metadata.

Only scans RFC 1918 private ranges. Never scans public IPs.
Designed to complete a /24 subnet scan in under 10 seconds.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import aiohttp

from discovery.netinfo import ipv4_prefixlen, resolve_source_ipv4
from qantara.http_safety import (
    HTTPResponseLimitError,
    decode_response_bytes,
    read_bounded_response_bytes,
)

# Known AI server ports and their likely types
KNOWN_PORTS: dict[int, str] = {
    11434: "ollama",
    8080: "llama.cpp",
    8000: "vllm",
    1234: "lmstudio",
    4000: "litellm",
    5000: "generic",
    3000: "generic",
    18789: "openclaw",
}

# Only scan private IP ranges
PRIVATE_RANGES = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)

# Concurrency limit for TCP probes
MAX_CONCURRENT_PROBES = 256

# Timeouts
TCP_TIMEOUT = 0.3  # seconds per TCP connect probe
HTTP_TIMEOUT = 1.5  # seconds per HTTP fingerprint request
# Never scan a network larger than a /24, even on a /22 or /16 LAN.
MAX_SCAN_PREFIX_WIDTH = 24
LOGGER = logging.getLogger(__name__)

# Single-flight guard: one LAN scan at a time per process. All callers run on
# the gateway's event loop, so a plain flag is enough.
_scan_in_progress = False


@dataclass
class DiscoveredModel:
    name: str
    size_gb: float | None = None
    param_size: str | None = None
    family: str | None = None
    state: str = "available"  # "loaded", "available"


@dataclass
class DiscoveredBackend:
    server_type: str  # "ollama", "llama.cpp", "vllm", "lmstudio", etc.
    url: str  # e.g., "http://192.168.1.50:1234"
    ip: str
    port: int
    models: list[DiscoveredModel] = field(default_factory=list)
    health: str = "unknown"  # "healthy", "degraded", "unreachable"
    latency_ms: float = 0.0
    is_localhost: bool = False
    version: str | None = None
    gpu_info: str | None = None  # e.g., "100% GPU, 6.6GB VRAM"
    model_loaded: str | None = None  # currently loaded model name
    confidence: str = "low"  # "high", "medium", "low"


def is_private_ip(ip: str) -> bool:
    """Check if an IP is in a private RFC 1918 range."""
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in PRIVATE_RANGES)
    except ValueError:
        return False


def get_local_ip() -> str:
    """Get the primary private IPv4 of this machine, or 127.0.0.1.

    Uses the routing table's source address first (the UDP-connect trick);
    ``gethostname()`` resolves to 127.0.1.1 on Debian/Ubuntu. Never returns
    a public address.
    """
    source_ip = resolve_source_ipv4()
    if source_ip and is_private_ip(source_ip):
        return source_ip
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for family, _, _, _, sockaddr in infos:
        if family != socket.AF_INET:
            continue
        ip = sockaddr[0]
        if is_private_ip(ip):
            return ip
    LOGGER.info("No private IPv4 address detected; scanning localhost only")
    return "127.0.0.1"


def get_local_prefixlen(local_ip: str) -> int | None:
    """Netmask prefix length of the interface that owns ``local_ip``, if known."""
    return ipv4_prefixlen(local_ip)


def scan_network(local_ip: str, prefixlen: int | None = None) -> ipaddress.IPv4Network | None:
    """The network to scan around ``local_ip``: the real subnet when it is a
    /24 or smaller, otherwise the /24 containing ``local_ip``. None for any
    address that is not RFC 1918 private (loopback is handled separately)."""
    if not is_private_ip(local_ip):
        return None
    width = MAX_SCAN_PREFIX_WIDTH
    if isinstance(prefixlen, int) and not isinstance(prefixlen, bool) and 0 <= prefixlen <= 32:
        width = max(prefixlen, MAX_SCAN_PREFIX_WIDTH)
    network = ipaddress.ip_network(f"{local_ip}/{width}", strict=False)
    if not any(network.subnet_of(net) for net in PRIVATE_RANGES):
        return None
    return network


def get_subnet_hosts(local_ip: str, prefixlen: int | None = None) -> list[str]:
    """Hosts to probe around ``local_ip``: at most a /24 of a private range,
    only 127.0.0.1 for a loopback fallback, and nothing for anything else."""
    try:
        if ipaddress.ip_address(local_ip).is_loopback:
            return ["127.0.0.1"]
    except ValueError:
        return []
    network = scan_network(local_ip, prefixlen)
    if network is None:
        return []
    return [str(h) for h in network.hosts() if is_private_ip(str(h))]


async def tcp_probe(host: str, port: int) -> bool:
    """Quick TCP connect probe. Returns True if port is open."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=TCP_TIMEOUT,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (TimeoutError, OSError):
        return False


async def http_get_json(
    session: aiohttp.ClientSession, url: str
) -> tuple[int, Any, float] | None:
    """GET a URL and return (status, json_body, latency_ms) or None."""
    start = time.perf_counter()
    try:
        async with session.get(url, allow_redirects=False) as resp:
            raw = await read_bounded_response_bytes(resp)
            text = decode_response_bytes(resp, raw)
            latency = (time.perf_counter() - start) * 1000
            try:
                body = json.loads(text) if text.strip() else None
            except json.JSONDecodeError:
                body = None
            return resp.status, body, latency
    except (TimeoutError, aiohttp.ClientError, HTTPResponseLimitError, OSError):
        return None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _extract_ollama_models(tags_body: Any) -> list[DiscoveredModel]:
    """Extract models from Ollama /api/tags response. Any LAN device can
    answer on these ports, so every field is type-checked."""
    if not isinstance(tags_body, dict):
        return []
    entries = tags_body.get("models")
    if not isinstance(entries, list):
        return []
    models = []
    for m in entries:
        if not isinstance(m, dict):
            continue
        name = _str_or_none(m.get("name")) or _str_or_none(m.get("model")) or ""
        if not name:
            continue
        size_bytes = _finite_number(m.get("size"))
        details = m.get("details")
        if not isinstance(details, dict):
            details = {}
        models.append(DiscoveredModel(
            name=name,
            size_gb=round(size_bytes / (1024 ** 3), 1) if size_bytes else None,
            param_size=_str_or_none(details.get("parameter_size")) or "",
            family=_str_or_none(details.get("family")) or "",
        ))
    return models


def _extract_openai_models(body: Any) -> list[DiscoveredModel]:
    """Extract models from OpenAI-compatible /v1/models response."""
    if not isinstance(body, dict):
        return []
    entries = body.get("data")
    if not isinstance(entries, list):
        return []
    models = []
    for m in entries:
        if not isinstance(m, dict):
            continue
        mid = _str_or_none(m.get("id"))
        if mid:
            models.append(DiscoveredModel(name=mid))
    return models


async def fingerprint_host(
    session: aiohttp.ClientSession, ip: str, port: int, local_ip: str | None
) -> DiscoveredBackend | None:
    """Identify what AI server is running on ip:port and extract metadata."""
    base = f"http://{ip}:{port}"
    is_local = ip == local_ip or ip in ("127.0.0.1", "localhost")

    # --- Try Ollama-specific endpoint ---
    result = await http_get_json(session, f"{base}/api/tags")
    if result and result[0] == 200:
        models = _extract_ollama_models(result[1])
        backend = DiscoveredBackend(
            server_type="ollama", url=base, ip=ip, port=port,
            models=models, health="healthy", latency_ms=round(result[2], 1),
            is_localhost=is_local, confidence="high",
        )
        # Get version
        ver = await http_get_json(session, f"{base}/api/version")
        if ver and ver[0] == 200 and isinstance(ver[1], dict):
            backend.version = _str_or_none(ver[1].get("version"))
        # Get GPU info from /api/ps
        ps = await http_get_json(session, f"{base}/api/ps")
        if ps and ps[0] == 200 and isinstance(ps[1], dict):
            running = ps[1].get("models")
            if isinstance(running, list) and running and isinstance(running[0], dict):
                first = running[0]
                backend.model_loaded = (
                    _str_or_none(first.get("name")) or _str_or_none(first.get("model")) or ""
                )
                vram = _finite_number(first.get("size_vram"))
                if vram:
                    backend.gpu_info = f"{round(vram / (1024**3), 1)}GB VRAM"
        return backend

    # --- Try LM Studio native API ---
    result = await http_get_json(session, f"{base}/api/v0/models")
    if result and result[0] == 200:
        models = _extract_openai_models(result[1])
        return DiscoveredBackend(
            server_type="lmstudio", url=base, ip=ip, port=port,
            models=models, health="healthy", latency_ms=round(result[2], 1),
            is_localhost=is_local, confidence="high",
        )

    # --- Try OpenAI-compatible /v1/models ---
    result = await http_get_json(session, f"{base}/v1/models")
    if result and result[0] == 200:
        models = _extract_openai_models(result[1])
        if models:
            # Guess type by port
            guessed_type = {
                8080: "llama.cpp", 8000: "vllm",
                4000: "litellm", 1234: "lmstudio",
            }.get(port, "openai-compatible")
            return DiscoveredBackend(
                server_type=guessed_type, url=base, ip=ip, port=port,
                models=models, health="healthy", latency_ms=round(result[2], 1),
                is_localhost=is_local, confidence="medium",
            )

    # --- Try /health (llama.cpp, generic) ---
    result = await http_get_json(session, f"{base}/health")
    if result and 200 <= result[0] < 300:
        return DiscoveredBackend(
            server_type=KNOWN_PORTS.get(port, "unknown"), url=base, ip=ip, port=port,
            health="healthy", latency_ms=round(result[2], 1),
            is_localhost=is_local, confidence="low",
        )

    return None


async def scan_lan(progress_callback=None) -> list[DiscoveredBackend]:
    """Scan the local subnet (at most a /24) for AI backends.

    Only one scan runs at a time; a concurrent call reports an "error"
    event and returns an empty list.

    Args:
        progress_callback: async callable(event_type, data) for progress updates.
            event_type: "progress", "found", "done", "error"
    """
    global _scan_in_progress
    if _scan_in_progress:
        if progress_callback:
            await progress_callback("error", {"message": "A LAN scan is already running"})
        return []
    _scan_in_progress = True
    try:
        return await _scan_lan(progress_callback)
    finally:
        _scan_in_progress = False


async def _scan_lan(progress_callback) -> list[DiscoveredBackend]:
    local_ip = get_local_ip()
    if not local_ip:
        if progress_callback:
            await progress_callback("error", {"message": "Could not detect local IP"})
        return []

    prefixlen = get_local_prefixlen(local_ip)
    hosts = get_subnet_hosts(local_ip, prefixlen)
    if not hosts:
        if progress_callback:
            await progress_callback("error", {"message": "No hosts in subnet"})
        return []

    network = scan_network(local_ip, prefixlen)
    subnet = str(network) if network is not None else f"{local_ip}/32"
    total_probes = len(hosts) * len(KNOWN_PORTS)
    completed = 0
    last_reported_pct = -1
    results: list[DiscoveredBackend] = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

    if progress_callback:
        await progress_callback("progress", {
            "status": "scanning",
            "subnet": subnet,
            "hosts": len(hosts),
            "ports": len(KNOWN_PORTS),
            "total_probes": total_probes,
        })

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT, connect=TCP_TIMEOUT + 0.2)

    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:

        async def probe_one(host: str, port: int) -> None:
            nonlocal completed, last_reported_pct
            async with semaphore:
                backend = None
                try:
                    if await tcp_probe(host, port):
                        backend = await fingerprint_host(session, host, port, local_ip)
                except Exception:  # noqa: BLE001 - one odd LAN device must not abort the scan
                    LOGGER.debug("scan: fingerprinting %s:%d failed", host, port, exc_info=True)
                if backend:
                    results.append(backend)
                    if progress_callback:
                        await progress_callback("found", asdict(backend))

                completed += 1
                # Report progress in 10% steps, each step exactly once.
                pct = (completed * 100 // total_probes) // 10 * 10
                if pct > last_reported_pct:
                    last_reported_pct = pct
                    if progress_callback:
                        await progress_callback("progress", {
                            "status": "scanning",
                            "percent": pct,
                            "found": len(results),
                        })

        outcomes = await asyncio.gather(
            *(probe_one(host, port) for host in hosts for port in KNOWN_PORTS),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                LOGGER.debug("scan: probe task failed: %r", outcome)

    # Sort: localhost first, then by type, then by latency
    results.sort(key=lambda b: (not b.is_localhost, b.server_type, b.latency_ms))

    if progress_callback:
        await progress_callback("done", {"count": len(results)})

    return results


def serialize_backend(b: DiscoveredBackend) -> dict[str, Any]:
    """Serialize a DiscoveredBackend to JSON-safe dict."""
    d = asdict(b)
    d["models"] = [asdict(m) for m in b.models]
    return d
