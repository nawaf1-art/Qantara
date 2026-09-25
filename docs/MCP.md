# MCP Bridge

Qantara's MCP bridge has two directions. The client adapter lets Qantara speak to an MCP-backed agent. The server exposes Qantara's own browser voice session as MCP tools. In both directions the browser voice loop still owns microphone capture, STT, turn-taking, TTS, and playback. MCP is control-plane only.

## Client Adapter

Use the adapter directly from environment variables:

```bash
QANTARA_ADAPTER=mcp_client \
QANTARA_MCP_TRANSPORT=stdio \
QANTARA_MCP_COMMAND="python tests/fixtures/mcp_chat_server.py" \
QANTARA_MCP_CHAT_TOOL=voice_chat \
make spike-run-venv
```

Streamable HTTP MCP servers use `QANTARA_MCP_URL` instead of `QANTARA_MCP_COMMAND`:

```bash
QANTARA_ADAPTER=mcp_client \
QANTARA_MCP_TRANSPORT=http \
QANTARA_MCP_URL=http://127.0.0.1:8000/mcp \
QANTARA_MCP_CHAT_TOOL=chat \
make spike-run-venv
```

The setup page can list tools for configured stdio servers and private/loopback streamable HTTP URLs. Browser-driven stdio commands are intentionally not accepted; set `QANTARA_MCP_COMMAND` in the gateway environment. `/api/status` reports only the command's program basename and an `mcp_command_configured` flag, never the full command line or its arguments.

## Sessions and cancellation

The adapter keeps one long-lived MCP client session per adapter — one stdio server process, or one streamable-HTTP session — and reuses it for every turn, so a server that keeps state in memory remembers earlier turns. The tool list is cached per connection. The session is reopened after a connection failure and closed when the adapter is released (for example when the backend is reconfigured).

Cancelling a turn (barge-in) sends MCP `notifications/cancelled` for the in-flight tool call and stops waiting for it, instead of letting the call run to completion in the background.

## Tool Arguments

The adapter inspects the MCP tool input schema and sends the transcript using the first matching string argument name:

- `message`
- `prompt`
- `input`
- `query`
- `text`
- `transcript`

If the tool schema has `turn_context` or `context`, Qantara also includes the current voice turn context.

When the schema also declares a session argument (`session_id`, `sessionId`, `conversation_id`, `conversationId`, `thread_id`, or `threadId`), Qantara sends a stable id for the voice session — the browser's `client_session_id` when known — so the server can keep one conversation per browser. When the schema declares `client_context`, Qantara sends the session's client context.

## Progress

MCP progress notifications are forwarded to the browser as `assistant_activity` events. The activity strip is non-spoken; only the final MCP tool text is synthesized.

## Server Side

Run Qantara's MCP server over stdio:

```bash
QANTARA_GATEWAY_URL=http://127.0.0.1:8765 \
QANTARA_GATEWAY_TOKEN="$QANTARA_AUTH_TOKEN" \
python mcp_server.py
```

For streamable HTTP:

```bash
QANTARA_GATEWAY_URL=http://127.0.0.1:8765 \
QANTARA_GATEWAY_TOKEN="$QANTARA_AUTH_TOKEN" \
QANTARA_MCP_SERVER_TRANSPORT=streamable-http \
QANTARA_MCP_SERVER_HOST=127.0.0.1 \
QANTARA_MCP_SERVER_PORT=8766 \
python mcp_server.py
```

The server exposes:

- `voice_get_status` — returns active browser sessions and playback/session state
- `voice_session_start` — returns a matching active browser session or a browser-open instruction when no mic session exists yet
- `voice_speak` — queues text into an active browser session and lets Qantara synthesize/play it
- `voice_get_transcript` — returns the recent transcript items and event timeline for a browser session
- `voice_interrupt` — clears current playback/generation for a targeted browser session
- `voice_set_voice` — changes the playback voice for a targeted browser session
- `voice_set_translation_mode` — sets assistant, directional, live, or disabled translation mode for a targeted browser session

The server also exposes read-only MCP resources:

- `qantara://voices`
- `qantara://languages`
- `qantara://avatars`
- `qantara://sessions`
- `qantara://sessions/{session_id}/status`
- `qantara://sessions/{session_id}/transcript`
- `qantara://mesh/peers`

When there is exactly one active browser session, tools can omit `session_id` and `client_session_id`. With multiple active sessions, pass one of those IDs from `voice_get_status`.

The gateway side is exposed through protected local endpoints under `/api/control/voice/*`. If `QANTARA_AUTH_TOKEN` is set on the gateway, MCP callers must send the same token through `QANTARA_GATEWAY_TOKEN`. Python programs can use the same endpoints directly through `qantara.control.VoiceControl` (see [Python SDK](PYTHON_SDK.md#voice-control-client)).

## Server binding and security

The streamable HTTP server has no inbound authentication of its own, so it binds to loopback:

- `QANTARA_MCP_SERVER_HOST` defaults to `127.0.0.1`, and an empty value also means `127.0.0.1` (an empty host would otherwise bind every interface).
- `0.0.0.0`, `::`, or any other non-loopback host refuses to start unless `QANTARA_MCP_SERVER_ALLOW_INSECURE=1` is set. Use that only on a trusted network, and prefer stdio.

The Docker Compose file runs only the gateway; the MCP server is a source-checkout process (`python mcp_server.py`).
