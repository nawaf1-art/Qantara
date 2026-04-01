from __future__ import annotations

import os

from adapters.base import AdapterConfig, RuntimeAdapter
from adapters.mock_adapter import MockAdapter
from adapters.session_gateway_http import SessionGatewayHTTPAdapter
from adapters.runtime_skeleton import RuntimeSkeletonAdapter


def load_adapter_config() -> AdapterConfig:
    kind = os.environ.get("QANTARA_ADAPTER", "mock").strip().lower() or "mock"
    return AdapterConfig(kind=kind, name=kind)


def create_adapter(config: AdapterConfig | None = None) -> RuntimeAdapter:
    config = config or load_adapter_config()

    if config.kind == "mock":
        return MockAdapter(config)
    if config.kind in {"runtime", "runtime_skeleton", "real"}:
        return RuntimeSkeletonAdapter(config)
    if config.kind in {"session_gateway", "session_gateway_http", "http"}:
        return SessionGatewayHTTPAdapter(config)

    raise ValueError(f"unsupported adapter kind: {config.kind}")
