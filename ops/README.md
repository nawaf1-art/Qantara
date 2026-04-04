# Ops

This directory contains operational setup for running Qantara outside a local-only browser session.

The immediate purpose is enabling `HTTPS` on the LAN so browser microphone access works on other devices.

## Why HTTPS Matters

Browser microphone access usually requires a secure context.

What this means for Qantara:

- `http://127.0.0.1` is acceptable for local testing on the same machine
- `http://192.168.x.x` is usually not acceptable for microphone access from another device
- for LAN use on other devices, Qantara should be served over `https://`
- when served over HTTPS, the client must connect to the gateway with `wss://`

The browser client already supports `wss://` automatically when the page is served over HTTPS.

## Recommended Approach

Use a reverse proxy in front of the Python gateway and terminate TLS there.

Recommended first choice:

- `Caddy`

Why:

- simple configuration
- automatic HTTPS support when certificate trust is set up correctly
- easy reverse proxy behavior for a single local service

If Caddy is not available, Qantara can also run the current spike directly with a self-signed certificate using Python's TLS support. That is less convenient than a trusted local CA, but it removes the `ERR_SSL_PROTOCOL_ERROR` class of failure.

## Gateway Topology

Recommended topology:

1. Run the Qantara spike gateway internally on a local port such as `8899`
2. Put `Caddy` in front of it
3. Expose a hostname such as `qantara.local`
4. Access the spike at `https://qantara.local`

Traffic shape:

```text
browser -> https://qantara.local -> Caddy -> http://127.0.0.1:8899
browser websocket -> wss://qantara.local/ws -> Caddy -> ws://127.0.0.1:8899/ws
```

## Example Caddy Setup

See:

- [`Caddyfile`](Caddyfile)

Example flow:

1. Make `qantara.local` resolve to the machine running Qantara
2. Run the Python spike on `127.0.0.1:8899`
3. Start Caddy with the provided config
4. Trust the generated local CA on devices that need browser mic access

## Direct TLS Fallback

If you do not have Caddy installed, you can generate a self-signed certificate and run the Python spike directly over HTTPS.

Config template:

- [`openssl-qantara.cnf`](openssl-qantara.cnf)

Example certificate generation:

```bash
mkdir -p ops/certs
openssl req -x509 -nodes -days 30 \
  -newkey rsa:2048 \
  -keyout ops/certs/qantara-key.pem \
  -out ops/certs/qantara-cert.pem \
  -config ops/openssl-qantara.cnf
```

Then run the spike with TLS:

```bash
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=9443 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
./.venv/bin/python gateway/transport_spike/server.py
```

Open:

```text
https://192.168.68.59:9443/spike
```

Important:

- a self-signed certificate still has to be trusted by the client device
- if the device does not trust the certificate, browser microphone access may still be blocked
- the best path remains a locally trusted CA or proper internal TLS setup

Windows trust help:

- [`TRUST_CERT_WINDOWS.md`](TRUST_CERT_WINDOWS.md)

## Practical Notes

- A self-signed certificate that the device does not trust will still cause browser problems
- The cleanest developer path is a locally trusted CA or internal PKI
- Do not expose the spike broadly to the internet in its current state

## Current Repo State

This operational setup is for the current M0 spike only.

It does not change the architecture decision:

- Qantara still remains a custom async gateway
- the current runtime path still remains mock-based
- this only makes LAN browser testing practical
