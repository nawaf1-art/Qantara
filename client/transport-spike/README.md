# Browser Transport Spike

## Purpose

Thin browser client for the M0 transport spike.

## Run

Serve this directory with any static file server, for example:

```bash
cd client/transport-spike
python3 -m http.server 8000
```

Then open:

```text
http://127.0.0.1:8000
```

The page connects to:

```text
ws://<host>:8765/ws
```

Where `<host>` defaults to the page host.
