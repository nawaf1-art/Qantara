from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("qantara-test-mcp", log_level="ERROR")


@mcp.tool(name="voice_chat")
async def voice_chat(message: str, turn_context: dict | None = None, ctx: Context | None = None) -> str:
    if ctx is not None:
        await ctx.report_progress(1, 2, "reading voice transcript")
    await asyncio.sleep(0)
    if ctx is not None:
        await ctx.report_progress(2, 2, "writing voice reply")
    output_language = (turn_context or {}).get("output_language", "en")
    return f"MCP reply ({output_language}): {message}"


if __name__ == "__main__":
    mcp.run()
