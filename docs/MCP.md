# MCP Bridge

Qantara's first MCP slice is an agent-style client adapter. The browser voice loop still owns microphone capture, STT, turn-taking, TTS, and playback. The MCP adapter calls one configured MCP chat tool with each finalized transcript and speaks the returned text.

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

The MCP server side is still the next `0.2.8` slice. It needs a gateway control endpoint that can address active browser sessions before tools like `voice_speak` can honestly make Qantara speak.
