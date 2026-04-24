from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable

from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

LOGGER = logging.getLogger(__name__)

DEFAULT_SERVICE_TYPE = "_qantara._tcp.local."

PeerCallback = Callable[[dict], Awaitable[None]]
RemovalCallback = Callable[[str], Awaitable[None]]


def _resolve_local_ipv4() -> str:
    """Best-effort local IPv4. We bind mDNS services to this address so
    peers on the LAN can reach us. Falls back to 127.0.0.1 if nothing
    else is available."""
    try:
        # Trick: UDP connect to a routable address doesn't actually send
        # traffic but forces the OS to pick the right source interface.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.168.1.1", 9))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        return "127.0.0.1"


def _build_txt_properties(
    node_id: str,
    role: str,
    capabilities: dict,
) -> dict[bytes, bytes]:
    # python-zeroconf expects bytes keys/values. Cap each value at 255
    # bytes (mDNS TXT record limit per entry) by truncating the JSON
    # capabilities blob if necessary.
    import json
    caps_blob = json.dumps(capabilities)
    if len(caps_blob) > 240:
        caps_blob = json.dumps({"truncated": True})
    return {
        b"node_id": node_id.encode("utf-8"),
        b"role": role.encode("utf-8"),
        b"caps": caps_blob.encode("utf-8"),
    }


class MeshAdvertiser:
    """Announces this node on _qantara._tcp.local. via mDNS so peers
    on the LAN can discover it."""

    def __init__(
        self,
        service_type: str,
        node_id: str,
        role: str,
        port: int,
        capabilities: dict,
        host_ip: str | None = None,
    ) -> None:
        self._service_type = service_type
        self._node_id = node_id
        self._role = role
        self._port = port
        self._capabilities = capabilities
        self._host_ip = host_ip or _resolve_local_ipv4()
        self._aiozc: AsyncZeroconf | None = None
        self._info: AsyncServiceInfo | None = None

    async def start(self) -> None:
        self._aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        instance_name = f"{self._node_id}.{self._service_type}"
        self._info = AsyncServiceInfo(
            type_=self._service_type,
            name=instance_name,
            addresses=[socket.inet_aton(self._host_ip)],
            port=self._port,
            properties=_build_txt_properties(self._node_id, self._role, self._capabilities),
            server=f"qantara-{self._node_id}.local.",
        )
        await self._aiozc.async_register_service(self._info)
        LOGGER.info(
            "mesh: advertising node %s as %s on %s:%d (type %s)",
            self._node_id, self._role, self._host_ip, self._port, self._service_type,
        )

    async def stop(self) -> None:
        if self._aiozc is None:
            return
        try:
            if self._info is not None:
                await self._aiozc.async_unregister_service(self._info)
        except Exception:
            LOGGER.debug("mesh: advertiser unregister raised; ignoring", exc_info=True)
        finally:
            await self._aiozc.async_close()
            self._aiozc = None
            self._info = None


class MeshBrowser:
    """Browses _qantara._tcp.local. and reports discovered peers.
    Ignores the local node (identified by node_id in TXT)."""

    def __init__(
        self,
        service_type: str,
        local_node_id: str,
        on_peer_added: PeerCallback,
        on_peer_removed: RemovalCallback,
    ) -> None:
        self._service_type = service_type
        self._local_node_id = local_node_id
        self._on_peer_added = on_peer_added
        self._on_peer_removed = on_peer_removed
        self._aiozc: AsyncZeroconf | None = None
        self._browser: AsyncServiceBrowser | None = None
        self._known_instances: dict[str, dict] = {}

    async def start(self) -> None:
        self._aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        self._browser = AsyncServiceBrowser(
            self._aiozc.zeroconf,
            self._service_type,
            handlers=[self._on_service_state_change],
        )

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.async_cancel()
            self._browser = None
        if self._aiozc is not None:
            await self._aiozc.async_close()
            self._aiozc = None

    def _on_service_state_change(  # type: ignore[no-untyped-def]
        self,
        zeroconf,  # noqa: ARG002
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        # Zeroconf callback is sync but we need async. Fire and forget a
        # task on the current loop.
        asyncio.get_running_loop().create_task(
            self._handle_change(service_type, name, state_change)
        )

    async def _handle_change(self, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change == ServiceStateChange.Removed:
            record = self._known_instances.pop(name, None)
            if record is not None:
                try:
                    await self._on_peer_removed(record["node_id"])
                except Exception:
                    LOGGER.exception("mesh: on_peer_removed raised")
            return
        if state_change not in (ServiceStateChange.Added, ServiceStateChange.Updated):
            return
        info = AsyncServiceInfo(service_type, name)
        if self._aiozc is None:
            return
        resolved = await info.async_request(self._aiozc.zeroconf, 2000)
        if not resolved:
            return
        props = info.properties or {}
        node_id = (props.get(b"node_id") or b"").decode("utf-8", errors="replace")
        if not node_id or node_id == self._local_node_id:
            return
        addresses = info.parsed_addresses()
        host = addresses[0] if addresses else ""
        record = {
            "node_id": node_id,
            "role": (props.get(b"role") or b"full").decode("utf-8", errors="replace"),
            "host": host,
            "port": info.port or 0,
            "capabilities_raw": (props.get(b"caps") or b"{}").decode("utf-8", errors="replace"),
        }
        self._known_instances[name] = record
        try:
            await self._on_peer_added(record)
        except Exception:
            LOGGER.exception("mesh: on_peer_added raised")
