"""mcd-mcp client: streamable HTTP transport via the official MCP SDK.

Flow per MCP spec:
  1. POST initialize (handled by ClientSession.initialize())
  2. notifications/initialized
  3. tools/list (validated once on connect)
  4. tools/call per data request

Auth: Authorization: Bearer <MCD_MCP_TOKEN>.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_TIMEOUT = 30.0

REQUIRED_TOOLS = {
    "query-nearby-stores",
    "query-meals",
    "query-meal-detail",
    "query-store-coupons",
    "query-my-coupons",
    "list-nutrition-foods",
    "calculate-price",
}


class McpToolError(RuntimeError):
    def __init__(self, tool: str, message: str):
        super().__init__(f"mcd-mcp tool '{tool}' failed: {message}")
        self.tool = tool


class McdMcpClient:
    def __init__(self, url: str, token: str, timeout: float = DEFAULT_TIMEOUT):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.available_tools: set[str] = set()
        self._stack = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> McdMcpClient:
        headers = {"Authorization": f"Bearer {self.token}"}
        self._stack = streamablehttp_client(self.url, headers=headers, timeout=self.timeout)
        read, write, _ = await self._stack.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        tools = await self._session.list_tools()
        self.available_tools = {t.name for t in tools.tools}
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session is not None:
            await self._session.__aexit__(*exc)
        if self._stack is not None:
            await self._stack.__aexit__(*exc)

    def missing_required_tools(self) -> set[str]:
        return REQUIRED_TOOLS - self.available_tools

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        assert self._session is not None, "client not connected"
        result = await self._session.call_tool(tool, args)
        if result.isError:
            message = " ".join(getattr(c, "text", "") for c in result.content) or "unknown error"
            raise McpToolError(tool, message.strip())
        text = next(
            (getattr(c, "text", "") for c in result.content if getattr(c, "type", "") == "text"),
            "",
        )
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw_text": text}


def call_tool_sync(url: str, token: str, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    """Run a sequence of tool calls on one connection, synchronously."""

    async def _run() -> list[Any]:
        async with McdMcpClient(url, token) as client:
            outputs = []
            for tool, args in calls:
                outputs.append(await client.call(tool, args))
            return outputs

    return asyncio.run(_run())
