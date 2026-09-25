# Qantara Mesh

**Status: Experimental.** The `0.4.0` election, reachability, and safety fixes are covered by unit and single-machine integration tests. The mesh has not yet been validated across physical devices on a real LAN, and replay protection is not implemented ([#26](https://github.com/nawaf1-art/Qantara/issues/26)).

Run two or more Qantara nodes on the same LAN. They discover each other via mDNS, elect a single responder per spoken utterance by audio RMS, and the winning node answers. The mesh needs the `mesh` extra (`pip install -e ".[mesh]"`, which installs `zeroconf`) and a native install; see [Docker caveat](#docker-caveat).

## Quick start

On each node, set:

```bash
export QANTARA_MESH_ROLE=full      # full | mic-only | speaker-only | disabled
export QANTARA_MESH_HOST=0.0.0.0   # required for LAN peers; default is 127.0.0.1
export QANTARA_MESH_PORT=8901      # default
export QANTARA_MESH_TOKEN="<same 24+ character secret on every node>"
export QANTARA_MESH_NODE_ID=desk   # optional stable id: 1-64 of A-Z a-z 0-9 . _ -
```

Generate the token once (for example `openssl rand -hex 24`) and copy the same value to every node. Start the gateway normally (`make spike-run-lan-venv`, or `qantara` with a LAN `--host`). The gateway itself also needs `QANTARA_AUTH_TOKEN` for browser access from other devices. Nodes find each other automatically within ~2 seconds.

## Startup rules

The gateway refuses to start when the mesh configuration is unsafe or invalid:

- A non-loopback `QANTARA_MESH_HOST` without `QANTARA_MESH_TOKEN` aborts startup. `QANTARA_MESH_ALLOW_INSECURE=1` overrides this for a trusted network, logs a warning, and leaves frames unauthenticated.
- `QANTARA_MESH_TOKEN`, when set, must be at least 24 characters (the same rule as `QANTARA_AUTH_TOKEN`).
- `QANTARA_MESH_ROLE` accepts `full`, `mic-only`, and `speaker-only`. `disabled`, `off`, `false`, `0`, `no`, `none`, or an empty value disable the mesh. Any other value aborts startup instead of being silently ignored.
- `QANTARA_MESH_NODE_ID` must match `^[A-Za-z0-9._-]{1,64}$`; a set but invalid id aborts startup, and an unset id is generated as `qantara-` plus 8 hex characters. Peers with invalid ids or roles in mDNS records or `hello` frames are ignored.
- A loopback bind (the default) starts the mesh TCP server but no mDNS advertiser or browser, and a node never advertises a loopback address.

When `QANTARA_MESH_TOKEN` is set, every mesh frame carries an HMAC-SHA256 signature keyed by the token, and nodes drop frames that are unsigned, tampered with, or signed with a different token. A mismatched token means peers discover each other over mDNS but ignore each other's election traffic. The token authenticates frames; it does not encrypt them, and a captured signed frame can currently be replayed. Do not expose the mesh port to the public internet.

## Roles

- **`full`** — runs STT, the adapter, and TTS locally. Can win elections and speak replies.
- **`mic-only`** — captures audio and forwards its RMS. It is dropped from the election whenever any `full` node is a candidate, so a mic-only phone and a full desktop never both yield. It can win only when no `full` node is present.
- **`speaker-only`** — never wins an election, even when it is the only node that heard the speech (then nobody claims).
- **`disabled`** — mesh is off. Single-node install.

## Election

When a node detects speech it runs the election in the background, so audio keeps flowing:

1. It broadcasts `rms_update` with its RMS to every known peer.
2. It waits 150 ms for peer `rms_update` frames. Each peer observation is stamped with the **receiver's** clock on arrival and counts for 1 s, so clock differences between nodes do not matter.
3. It applies the same rule on every node: drop `speaker-only` nodes; drop `mic-only` nodes if any `full` node is a candidate; the highest RMS wins; ties go to the lexicographically smallest `node_id`.
4. The winner broadcasts `turn_claim`; the others broadcast `turn_yield`.

A finalized voice turn waits at most 300 ms for a still-running election. If the election has not finished, the node records `mesh_election_timeout` and responds itself rather than delaying the user. A losing node emits `turn_deferred_to_peer` and does not submit the turn.

All messages are advisory. A missed `turn_claim` means two nodes may speak on that turn — annoying, not catastrophic, and self-correcting on the next utterance.

## Unreachable peers

A sleeping or firewalled peer cannot stall the voice loop:

- Connecting to a peer times out after 0.5 s.
- A broadcast goes to all peers concurrently and is abandoned after 0.5 s.
- A peer that fails is skipped for 1 s, then 2, 4, and 8 s after repeated failures; a successful send or a new `hello` from it resets the backoff.
- The election returns after its 150 ms window regardless of peer health; claim/yield announcements are sent in the background.
- A connection that sends a malformed, oversized, or wrongly signed frame is closed.

`hello` frames now carry the sender's listening port so that a peer learned from an inbound connection is reachable. Nodes running a release before `0.4.0` reject the new `hello` and rely on mDNS discovery instead; upgrade every node together.

## Docker caveat

The mesh is native-only. mDNS does not cross the default Docker bridge, and the bundled `docker-compose.yml` does not configure the mesh. A custom container would need `network_mode: host` or a macvlan network, which is not a validated configuration.

## Troubleshooting

Run `qantara doctor --mesh` (source checkout: `make doctor ARGS=--mesh` or `python scripts/doctor.py --mesh`) against a running gateway to see its role, node id, and peers. If peers are `UNREACHABLE`, it's usually a firewall on the mesh port. Open port `8901/tcp` on each node (or whatever you set via `QANTARA_MESH_PORT`).

If each node only sees itself, confirm `QANTARA_MESH_HOST=0.0.0.0` (or the node's LAN address) is set. The loopback default starts no mDNS discovery, which is correct for single-node installs but invisible to LAN peers.

If the gateway refuses to start, read the error: it names the missing token, the too-short token, the invalid role, or the invalid node id.

If mDNS discovery itself fails:
- Linux with Avahi: usually fine; confirm `avahi-daemon` is running.
- macOS: fine out of the box.
- Windows: may need Bonjour (bundled with iTunes, or install Bonjour Print Services separately).
- Corporate networks sometimes block multicast UDP/5353.

The wire format is specified in [`schemas/MESH_PROTOCOL.md`](../schemas/MESH_PROTOCOL.md).
