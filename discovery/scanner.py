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
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import aiohttp

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
LOGGER = logging.getLogger(__name__)


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


def get_local_ip() -> str | None:
    """Get the primary private IP of this machine."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for family, _, _, _, sockaddr in infos:
        if family != socket.AF_INET:
            continue
        ip = sockaddr[0]
        if ip.startswith("127."):
            continue
        if is_private_ip(ip):
            return ip
    LOGGER.info("No private IPv4 address detected from getaddrinfo; falling back to 127.0.0.1")
    return "127.0.0.1"


def get_subnet_hosts(local_ip: str) -> list[str]:
    """Get all hosts in the /24 subnet of the given IP."""
    try:
        network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
        return [str(h) for h in network.hosts()]
    except ValueError:
        return []


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
        async with session.get(url) as resp:
            text = await resp.text()
            latency = (time.perf_counter() - start) * 1000
            try:
                body = json.loads(text) if text.strip() else None
            except json.JSONDecodeError:
                body = None
            return resp.status, body, latency
    except (TimeoutError, aiohttp.ClientError, OSError):
        return None


def _extract_ollama_models(tags_body: Any) -> list[DiscoveredModel]:
    """Extract models from Ollama /api/tags response."""
    if not isinstance(tags_body, dict):
        return []
    models = []
    for m in tags_body.get("models", []):
        name = m.get("name", "")
        if not name:
            continue
        size_bytes = m.get("size", 0)
        models.append(DiscoveredModel(
            name=name,
            size_gb=round(size_bytes / (1024 ** 3), 1) if size_bytes else None,
            param_size=m.get("details", {}).get("parameter_size", ""),
            family=m.get("details", {}).get("family", ""),
        ))
    return models


def _extract_openai_models(body: Any) -> list[DiscoveredModel]:
    """Extract models from OpenAI-compatible /v1/models response."""
    if not isinstance(body, dict):
        return []
    models = []
    for m in body.get("data", []):
        mid = m.get("id", "")
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
            backend.version = ver[1].get("version")
        # Get GPU info from /api/ps
        ps = await http_get_json(session, f"{base}/api/ps")
        if ps and ps[0] == 200 and isinstance(ps[1], dict):
            running = ps[1].get("models", [])
            if running:
                first = running[0]
                backend.model_loaded = first.get("name", "")
                vram = first.get("size_vram", 0)
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
    """Scan the local /24 subnet for AI backends.

    Args:
        progress_callback: async callable(event_type, data) for progress updates.
            event_type: "progress", "found", "done", "error"
    """
    local_ip = get_local_ip()
    if not local_ip:
        if progress_callback:
            await progress_callback("error", {"message": "Could not detect local IP"})
        return []

    hosts = get_subnet_hosts(local_ip)
    if not hosts:
        if progress_callback:
            await progress_callback("error", {"message": "No hosts in subnet"})
        return []

    total_probes = len(hosts) * len(KNOWN_PORTS)
    completed = 0
    results: list[DiscoveredBackend] = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

    if progress_callback:
        await progress_callback("progress", {
            "status": "scanning",
            "subnet": f"{local_ip}/24",
            "hosts": len(hosts),
            "ports": len(KNOWN_PORTS),
            "total_probes": total_probes,
        })

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT, connect=TCP_TIMEOUT + 0.2)

    async with aiohttp.ClientSession(timeout=timeout) as session:

        async def probe_one(host: str, port: int) -> None:
            nonlocal completed
            async with semaphore:
                if await tcp_probe(host, port):
                    backend = await fingerprint_host(session, host, port, local_ip)
                    if backend:
                        results.append(backend)
                        if progress_callback:
                            await progress_callback("found", asdict(backend))

                completed += 1
                # Report progress every 10%
                pct = int(completed / total_probes * 100)
                if pct % 10 == 0 and progress_callback:
                    await progress_callback("progress", {
                        "status": "scanning",
                        "percent": pct,
                        "found": len(results),
                    })

        tasks = [
            probe_one(host, port)
            for host in hosts
            for port in KNOWN_PORTS
        ]
        await asyncio.gather(*tasks)

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
