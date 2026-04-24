# Mesh Protocol

Qantara nodes on the same LAN exchange a small number of JSONL-over-TCP
messages to coordinate which node should respond to a given spoken
utterance. The protocol is deliberately minimal — all semantics are
advisory; losing a message never corrupts state, only costs latency or
wastes a turn.

## Transport

- TCP, JSONL (one UTF-8 JSON object per line, terminated by `\n`).
- Default port: 8901 (override via `QANTARA_MESH_PORT`).
- Each node opens at most one TCP connection to each known peer.
- Connections are long-lived; reconnect on drop with 1/2/4/8s backoff.

## Message types

### `hello`
Sent as the first frame on every new connection.
```json
{"type": "hello", "node_id": "<uuid>", "role": "full|mic-only|speaker-only", "capabilities": {"stt": true, "tts": true}}
```

### `goodbye`
Sent before a clean disconnect. Peers remove the node from their registry.

### `rms_update`
Broadcast on local `speech_start_detected`. Peers compare against their
own RMS.
```json
{"type": "rms_update", "node_id": "<uuid>", "rms": 0.82, "session_id": "<uuid>", "monotonic_ms": 1234.5}
```

### `turn_claim`
Emitted ~150ms after the local speech start once the election window
closes and this node has the highest RMS.
```json
{"type": "turn_claim", "node_id": "<uuid>", "session_id": "<uuid>", "rms": 0.82, "monotonic_ms": 1234.5}
```

### `turn_yield`
Emitted by a node that heard speech start but lost the election. Purely
informational; carries the winner's node_id for audit.
```json
{"type": "turn_yield", "node_id": "<uuid>", "session_id": "<uuid>", "winner_node_id": "<uuid>"}
```

## Design notes

- No global clock — `monotonic_ms` is wall-monotonic-local, used only as
  a tiebreaker within a narrow (~300ms) window. Absolute values are not
  meaningful across nodes.
- Ties on RMS are broken by lexicographic `node_id` so all nodes compute
  the same winner deterministically.
- A missed `turn_claim` simply means two nodes speak simultaneously on
  this utterance — annoying but self-correcting on the next one.
