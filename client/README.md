# Client

This directory is for the browser-first Qantara client.

Initial scope:

- microphone capture
- WebSocket session bootstrap
- PCM audio send and receive
- playback queue
- captions and session state indicators
- browser-side VAD integration if adopted

Constraints:

- keep the client thin
- do not move agent logic into the browser
- do not bind the client to a specific downstream runtime
