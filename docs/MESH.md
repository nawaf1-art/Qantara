# Qantara Mesh (0.2.2)

Run two or more Qantara nodes on the same LAN. They discover each
other via mDNS, elect a single responder per spoken utterance by
audio RMS, and route TTS back to whichever speaker is closest.

## Quick start

On each node, set:

```bash
export QANTARA_MESH_ROLE=full      # full | mic-only | speaker-only | disabled
export QANTARA_MESH_HOST=0.0.0.0   # required for LAN peers; default is 127.0.0.1
export QANTARA_MESH_PORT=8901      # default
```

Start the gateway normally (`make spike-run-lan-venv`). Nodes find
each other automatically within ~2 seconds.

Mesh traffic is plaintext and intended only for a trusted LAN. Do not expose the mesh port to the public internet.

## Roles

- **`full`** — default. Runs STT, the adapter, and TTS locally. Can win
  elections and speak replies.
- **`mic-only`** — captures audio and forwards its RMS, but always
  yields to any `full` peer. A phone running Qantara could be
  `mic-only` so the desktop handles the reply.
- **`speaker-only`** — never wins elections (can't run STT). Useful
  when a tablet should only play announcements driven by HA or another
  node.
- **`disabled`** — mesh is off. Single-node install.

## Election

On `speech_start_detected`, a node:
1. Broadcasts `rms_update` with its RMS.
2. Sleeps 150ms to collect peer `rms_update` frames.
3. The highest RMS wins. Ties break lexicographically by `node_id`.
4. Winner broadcasts `turn_claim`; losers broadcast `turn_yield`.

All messages are advisory. A missed `turn_claim` means two nodes
speak at once on that turn — annoying, not catastrophic, and
self-corrects on the next utterance.

## Docker caveat

mDNS does not cross the default Docker bridge. Run with
`network_mode: host` or a macvlan network, otherwise peers will
never see each other.

## Troubleshooting

Check `make doctor --mesh`. If peers are `UNREACHABLE`, it's
usually a firewall on the mesh port. Open port `8901/tcp` on each
node (or whatever you set via `QANTARA_MESH_PORT`).

If each node only sees itself, confirm `QANTARA_MESH_HOST=0.0.0.0` is set. The safe default is loopback, which is correct for single-node installs but invisible to LAN peers.

If mDNS discovery itself fails:
- Linux with Avahi: usually fine; confirm `avahi-daemon` is running.
- macOS: fine out of the box.
- Windows: may need Bonjour (bundled with iTunes, or install
  Bonjour Print Services separately).
- Corporate networks sometimes block multicast UDP/5353.
