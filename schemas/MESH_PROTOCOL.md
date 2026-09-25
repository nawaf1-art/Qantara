# Mesh Protocol

Qantara nodes on the same LAN exchange a small number of JSONL-over-TCP
messages to coordinate which node should respond to a given spoken
utterance. The protocol is deliberately minimal — all semantics are
advisory; losing a message never corrupts state, only costs latency or
wastes a turn. Operator guidance is in [`docs/MESH.md`](../docs/MESH.md).

## Transport

- TCP, JSONL (one UTF-8 JSON object per line, terminated by `\n`).
- Default port: 8901 (override via `QANTARA_MESH_PORT`).
- Each node opens at most one outbound TCP connection to each known peer and
  sends `hello` as the first frame.
- Connects time out after 0.5 s. A broadcast is sent to every peer
  concurrently and abandoned after 0.5 s.
- A peer whose connect or send fails is skipped for 1 s, then 2, 4, and 8 s on
  repeated failures (8 s thereafter). A successful send or a new `hello` from
  that peer resets the backoff; the connection is re-opened on the next send.
- The receiving side closes a connection after the first frame that is not
  valid JSON, not an object, oversized, of an unknown type, malformed, fails
  field validation, or fails signature verification.

## Authentication

When `QANTARA_MESH_TOKEN` is configured, every frame carries a `sig` field:
an HMAC-SHA256 over the frame's canonical JSON form (without `sig`), keyed by
the token. Frames with a missing or mismatched signature are rejected.
Signatures authenticate but do not encrypt frames, and there is no replay
protection yet ([#26](https://github.com/nawaf1-art/Qantara/issues/26)).

## Field validation

- `node_id` and `winner_node_id`: `^[A-Za-z0-9._-]{1,64}$`.
- `role`: `full`, `mic-only`, or `speaker-only`.
- `port`: an integer TCP port (1–65535).
- `rms` and `monotonic_ms`: finite numbers; `rms` is non-negative and bounded.
- `capabilities`: an object.

The same node id and role rules apply to mDNS TXT records; invalid records
are ignored.

## Message types

### `hello`
Sent as the first frame on every new connection.
```json
{"type": "hello", "node_id": "desk", "role": "full|mic-only|speaker-only", "capabilities": {"stt": true, "tts": true}, "port": 8901}
```

`port` (optional, added in `0.4.0`) is the sender's mesh listening port. The
receiver only sees the inbound socket's ephemeral source port, so without it a
peer learned from a `hello` could not be reached. A peer record with port `0`
is never stored. Nodes older than `0.4.0` reject a `hello` that carries
`port` as malformed and fall back to mDNS discovery.

### `goodbye`
Sent before a clean disconnect. Peers remove the node from their registry.
```json
{"type": "goodbye", "node_id": "desk"}
```

### `rms_update`
Broadcast when local speech starts. Peers record the RMS for the election.
```json
{"type": "rms_update", "node_id": "desk", "rms": 0.82, "session_id": "<uuid>", "monotonic_ms": 1234.5}
```

### `turn_claim`
Broadcast by the winner once its 150 ms election window closes. Receivers
also record the claim's RMS, so a later election on that node yields to it.
```json
{"type": "turn_claim", "node_id": "desk", "session_id": "<uuid>", "rms": 0.82, "monotonic_ms": 1234.5}
```

### `turn_yield`
Broadcast by a node that lost the election. Purely informational; carries
the winner's node_id for audit.
```json
{"type": "turn_yield", "node_id": "kitchen", "session_id": "<uuid>", "winner_node_id": "desk"}
```

## Election rules

Every node computes the winner from the same inputs:

1. Candidates are the local node and every peer with an RMS observation
   received within the last 1 s (observations are timed with the
   **receiver's** monotonic clock on arrival).
2. `speaker-only` nodes are never candidates. A peer without a known role is
   treated as `full`.
3. If any `full` candidate exists, all `mic-only` candidates are dropped.
4. The highest RMS wins; ties go to the lexicographically smallest `node_id`.
5. With no candidates (for example a lone `speaker-only` node), nobody claims.

## Design notes

- No global clock. `monotonic_ms` is the sender's local monotonic time and is
  informational only; receivers never compare it with their own clock.
- A missed `turn_claim` simply means two nodes speak simultaneously on
  this utterance — annoying but self-correcting on the next one.
