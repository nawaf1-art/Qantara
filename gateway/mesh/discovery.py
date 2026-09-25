from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable

from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from discovery.netinfo import is_loopback_host, resolve_source_ipv4
from gateway.mesh.protocol import is_valid_node_id, is_valid_port, is_valid_role

LOGGER = logging.getLogger(__name__)

DEFAULT_SERVICE_TYPE = "_qantara._tcp.local."

PeerCallback = Callable[[dict], Awaitable[None]]
RemovalCallback = Callable[[str], Awaitable[None]]


def _resolve_local_ipv4() -> str:
    """Best-effort local IPv4. We advertise this address so peers on the
    LAN can reach us. Returns 127.0.0.1 if nothing else is available, which
    the advertiser then refuses to publish."""
    return resolve_source_ipv4() or "127.0.0.1"


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
        self._requested_host_ip = host_ip
        self._host_ip: str | None = None
        self._aiozc: AsyncZeroconf | None = None
        self._info: AsyncServiceInfo | None = None

    async def start(self) -> None:
        host_ip = self._requested_host_ip or _resolve_local_ipv4()
        if is_loopback_host(host_ip):
            # Advertising 127.0.0.1 makes every peer connect to itself
            # (audit M-a). Nothing on the LAN can reach a loopback node.
            LOGGER.warning(
                "mesh: not advertising node %s: no LAN address (resolved %s)",
                self._node_id, host_ip,
            )
            return
        self._host_ip = host_ip
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
        self._tasks: set[asyncio.Task] = set()

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
        for task in list(self._tasks):
            task.cancel()
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
        # Zeroconf callback is sync but we need async. Run a task on the
        # current loop, keeping a strong reference until it finishes.
        task = asyncio.get_running_loop().create_task(
            self._handle_change(service_type, name, state_change)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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
        role = (props.get(b"role") or b"full").decode("utf-8", errors="replace")
        addresses = info.parsed_addresses()
        host = addresses[0] if addresses else ""
        port = info.port
        # TXT records are unauthenticated LAN input and end up on the setup
        # page, so drop anything that is not a well-formed identity (Q-09).
        if not is_valid_node_id(node_id) or not is_valid_role(role):
            LOGGER.debug("mesh: ignoring mDNS record %r with invalid node_id/role", name)
            return
        if not host or not is_valid_port(port) or node_id == self._local_node_id:
            return
        record = {
            "node_id": node_id,
            "role": role,
            "host": host,
            "port": port,
            "capabilities_raw": (props.get(b"caps") or b"{}").decode("utf-8", errors="replace"),
        }
        self._known_instances[name] = record
        try:
            await self._on_peer_added(record)
        except Exception:
            LOGGER.exception("mesh: on_peer_added raised")
