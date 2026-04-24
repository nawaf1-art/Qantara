# Qantara as a Home Assistant voice satellite

Qantara's `0.2.2` release includes a Wyoming-protocol satellite endpoint
that Home Assistant auto-discovers over mDNS. This lets HA drive your
Qantara node through its Assist pipeline — the mic is yours, STT/LLM/TTS
run on HA's side (or whatever pipeline HA has configured).

## Enabling the Wyoming bridge

Set two environment variables before starting the gateway:

```bash
export QANTARA_WYOMING_ENABLED=true
export QANTARA_WYOMING_PORT=10700           # default
export QANTARA_WYOMING_NODE_NAME=kitchen    # shows up in HA as the satellite name
export QANTARA_WYOMING_AREA=kitchen         # optional; maps to HA area
```

Start the gateway as usual:

```bash
make spike-run-lan-venv
```

HA should discover the satellite within ~10 seconds. Look in
**Settings → Devices & Services** for a prompt to add "Wyoming Protocol".

## Manual setup in HA (if auto-discovery fails)

1. Settings → Devices & Services → Add Integration → **Wyoming Protocol**
2. Enter the Qantara host and the Wyoming port (default `10700`)
3. HA will issue a `describe` RPC and show the satellite name

## Docker caveat

mDNS does **not** cross the default Docker bridge network. If you're
running Qantara in Docker, use `network_mode: host` (or a macvlan
network) so both the Wyoming service discovery and the mesh work:

```yaml
services:
  qantara:
    image: ghcr.io/nawaf1-art/qantara:latest
    network_mode: host
    environment:
      - QANTARA_WYOMING_ENABLED=true
      - QANTARA_WYOMING_PORT=10700
```

## Limitations in 0.2.2

- Wake-word handling is not implemented — HA drives the whole pipeline.
  If you want a local wake word for zero-cloud latency, that lands in
  `0.3.x`.
- The satellite advertises `has_vad: false`; HA's server-side VAD runs.
- No timer events, no announce-mode TTS, no multi-turn context carry.
  All tracked on the `0.3.x` polish list.
