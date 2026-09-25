"""Local network facts shared by the LAN scanner and the mesh advertiser.

Stdlib only, so it can be imported without optional dependencies.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import sys

# Any routable address works: a UDP connect() sends no packet, it only asks
# the kernel which source address it would use for that route.
_ROUTE_PROBE_ADDR = ("192.168.1.1", 9)

_SIOCGIFADDR = 0x8915
_SIOCGIFNETMASK = 0x891B


def resolve_source_ipv4(probe_addr: tuple[str, int] = _ROUTE_PROBE_ADDR) -> str | None:
    """Return the IPv4 source address the OS would use for LAN traffic, or
    None when there is no usable route. Unlike ``gethostbyname(hostname)``
    this is not fooled by Debian/Ubuntu's ``127.0.1.1 <hostname>`` entry."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    try:
        sock.connect(probe_addr)
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if not isinstance(ip, str) or ip in {"", "0.0.0.0"}:
        return None
    return ip


def ipv4_prefixlen(ip: str) -> int | None:
    """Best-effort netmask prefix length of the interface that owns ``ip``.

    Linux only (SIOCGIFNETMASK); returns None elsewhere or on any failure,
    in which case callers fall back to /24.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        import fcntl
    except ImportError:
        return None
    try:
        names = [name for _index, name in socket.if_nameindex()]
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    try:
        for name in names:
            ifreq = struct.pack("256s", name.encode("utf-8")[:15])
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), _SIOCGIFADDR, ifreq)[20:24])
                if addr != ip:
                    continue
                mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), _SIOCGIFNETMASK, ifreq)[20:24])
                return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
            except (OSError, ValueError):
                continue
    finally:
        sock.close()
    return None


def is_loopback_host(host: str | None) -> bool:
    """True for loopback addresses and the ``localhost`` name. Wildcard and
    LAN addresses are not loopback."""
    host = (host or "").strip().strip("[]").lower()
    if host in {"localhost", "localhost."} or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
