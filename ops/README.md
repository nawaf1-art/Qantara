# Operations: Trusted-LAN HTTPS

This directory contains the supported operational examples for using Qantara from another device on a trusted local network. The native and Docker defaults remain loopback-only.

Browser microphone access normally requires either `localhost` or a secure HTTPS origin. A phone, tablet, or second computer therefore needs HTTPS/WSS plus certificate trust.

## Security boundary

Qantara is not documented as a public-internet service. Before changing a bind address from loopback:

1. Set a unique random `QANTARA_AUTH_TOKEN` of at least 24 characters.
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

Docker publishes to `127.0.0.1:8765` by default. Changing `QANTARA_DOCKER_BIND` is an explicit exposure decision and still requires authentication and HTTPS/WSS for another device's microphone.

## Mesh and Wyoming

Mesh and Wyoming are separate Experimental services. They bind to loopback unless explicitly changed. Use a shared `QANTARA_MESH_TOKEN` on every mesh node when enabling LAN frames, and expose Wyoming only to the Home Assistant network segment that needs it. See [`docs/MESH.md`](../docs/MESH.md) and [`docs/HOMEASSISTANT.md`](../docs/HOMEASSISTANT.md).

## Verification

- Confirm `https://` loads without a certificate warning.
- Confirm the auth unlock flow is required.
- Confirm microphone permission succeeds and the WebSocket uses `wss://`.
- Confirm the gateway/backend status exposes no token or credential.
- Confirm the service is unreachable from networks that are not intended to use it.
- Run the browser voice loop and barge-in checks from [`docs/QUICKSTART.md`](../docs/QUICKSTART.md).
