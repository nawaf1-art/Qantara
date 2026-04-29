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

The setup page can list tools for configured stdio servers and private/loopback streamable HTTP URLs. Browser-driven stdio commands are intentionally not accepted; set `QANTARA_MCP_COMMAND` in the gateway environment.

## Tool Arguments

The adapter inspects the MCP tool input schema and sends the transcript using the first matching string argument name:

- `message`
- `prompt`
- `input`
- `query`
- `text`
- `transcript`

If the tool schema has `turn_context` or `context`, Qantara also includes the current voice turn context.

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
- `voice_speak` — queues text into an active browser session and lets Qantara synthesize/play it
- `voice_interrupt` — clears current playback/generation for a targeted browser session
- `voice_set_voice` — changes the playback voice for a targeted browser session

When there is exactly one active browser session, tools can omit `session_id` and `client_session_id`. With multiple active sessions, pass one of those IDs from `voice_get_status`.

The gateway side is exposed through protected local endpoints under `/api/control/voice/*`. If `QANTARA_AUTH_TOKEN` is set on the gateway, MCP callers must send the same token through `QANTARA_GATEWAY_TOKEN`.
