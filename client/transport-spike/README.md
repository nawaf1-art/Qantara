# Browser Client

## Purpose

Qantara's vanilla JavaScript browser voice client. The directory name is
historical; the client is the current public UI.

## Run

Preferred:

Run the gateway and open:

```text
http://127.0.0.1:8765/spike
```

Alternative:

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
