# Operations: Trusted-LAN HTTPS

This directory contains the supported operational examples for using Qantara from another device on a trusted local network. The native and Docker defaults remain loopback-only.

Browser microphone access normally requires either `localhost` or a secure HTTPS origin. A phone, tablet, or second computer therefore needs HTTPS/WSS plus certificate trust.

## Security boundary

Qantara is not documented as a public-internet service. Before changing a bind address from loopback:

1. Set a unique random `QANTARA_AUTH_TOKEN` of at least 24 characters. This is **required**, not optional: the gateway refuses any request whose `Host` is not a loopback name or address when no token is configured. That includes traffic forwarded by a reverse proxy (Caddy preserves the browser's `Host`, e.g. `qantara.local`) and a Docker port published beyond `127.0.0.1`.
2. Terminate HTTPS with a certificate trusted by each client device.
3. Limit firewall/routing exposure to the intended trusted network.
4. Keep backend model/agent services private; expose only the gateway path required by clients.
5. Review exact Host and Origin policy when a reverse proxy or custom internal DNS name is used.

Do not commit tokens, private keys, generated certificates, public URLs, or machine-specific paths.

## Recommended topology: Caddy

Run the Qantara gateway on loopback and place Caddy in front of it:

```text
browser -> https://qantara.local -> Caddy -> http://127.0.0.1:8899
browser -> wss://qantara.local/ws -> Caddy -> ws://127.0.0.1:8899/ws
```

The included [`Caddyfile`](Caddyfile) is the starting point. A typical flow is:

1. Make `qantara.local` resolve to the Qantara host on the trusted LAN.
2. Start Qantara on `127.0.0.1:8899` with authentication enabled.
3. Start Caddy with the repository configuration.
4. Install/trust Caddy's local CA on each client device.
5. Open `https://qantara.local` and grant microphone permission.

Example gateway start:

```bash
QANTARA_AUTH_TOKEN="$(openssl rand -hex 24)" \
QANTARA_SPIKE_HOST=127.0.0.1 \
QANTARA_SPIKE_PORT=8899 \
./.venv/bin/python cli.py --backend mock
```

Store a stable production token through the host's secret-management mechanism rather than copying a generated shell value between sessions.

## Direct TLS fallback

Qantara can terminate TLS directly when a reverse proxy is not available. The template is [`openssl-qantara.cnf`](openssl-qantara.cnf).

Generate a short-lived local certificate:

```bash
mkdir -p ops/certs
openssl req -x509 -nodes -days 30 \
  -newkey rsa:2048 \
  -keyout ops/certs/qantara-key.pem \
  -out ops/certs/qantara-cert.pem \
  -config ops/openssl-qantara.cnf
```

Start the gateway:

```bash
QANTARA_AUTH_TOKEN="$(openssl rand -hex 24)" \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
./.venv/bin/python cli.py --backend mock
```

Open `https://<trusted-lan-ip>:9443`. The certificate must contain the hostname/IP used by the browser and must be trusted on the client. Windows trust notes are in [`TRUST_CERT_WINDOWS.md`](TRUST_CERT_WINDOWS.md).

## Host and Origin policy

The inbound Host guard accepts loopback, private LAN addresses, single-label local names, and names ending in `.local`, `.lan`, or `.home.arpa`.

- Add an exact extra internal hostname with `QANTARA_ALLOWED_HOSTS` only when it still resolves inside the trusted network.
- Add an exact full origin to `QANTARA_ALLOWED_ORIGINS` only when a deliberate proxy topology causes browser Origin to differ from request authority.
- Do not use either setting to approve a public hostname casually.

## Docker exposure

Docker publishes to `127.0.0.1:8765` by default, so `http://127.0.0.1:8765` works on the Docker host without a token. Changing `QANTARA_DOCKER_BIND` (for example to `0.0.0.0`) is an explicit exposure decision: set `QANTARA_AUTH_TOKEN` in the environment `docker compose` reads (the compose file passes it through), otherwise requests from other devices are refused. Another device's microphone additionally needs HTTPS/WSS, e.g. Caddy in front of the published port.

```bash
export QANTARA_AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
QANTARA_DOCKER_BIND=0.0.0.0 docker compose up
```

Model weights (faster-whisper, Kokoro) are cached in the `qantara-model-cache` named volume, so they download once and survive `docker compose down`. `docker compose down --volumes` removes them.

## Mesh

The mesh is an Experimental, native-only service: it relies on mDNS multicast discovery, which container bridge networking blocks, so the compose file does not configure it. It binds to loopback unless explicitly changed. Use a shared `QANTARA_MESH_TOKEN` on every mesh node when enabling LAN frames. See [`docs/MESH.md`](../docs/MESH.md).

## Verification

- Run `qantara doctor` (or `python scripts/doctor.py`) with the same environment; it fails when a non-loopback bind has no valid token and warns when TLS is missing.
- Confirm `https://` loads without a certificate warning.
- Confirm the auth unlock flow is required.
- Confirm microphone permission succeeds and the WebSocket uses `wss://`.
- Confirm the gateway/backend status exposes no token or credential.
- Confirm the service is unreachable from networks that are not intended to use it.
- Run the browser voice loop and barge-in checks from [`docs/QUICKSTART.md`](../docs/QUICKSTART.md).
