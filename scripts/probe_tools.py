"""Probe mcd-mcp tool schemas (dev only, requires MCD_MCP_TOKEN)."""

import asyncio
import json
import os
import sys

sys.path.insert(0, "src")

from mcoptimizer.mcp_client import McdMcpClient  # noqa: E402


async def main() -> None:
    token = os.environ["MCD_MCP_TOKEN"]
    url = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")
    async with McdMcpClient(url, token) as client:
        session = client._session
        tools = await session.list_tools()
        wanted = {
            "query-nearby-stores",
            "query-meals",
            "query-store-coupons",
            "list-nutrition-foods",
            "calculate-price",
        }
        for t in tools.tools:
            if t.name in wanted:
                print("=" * 60)
                print(t.name)
                print(json.dumps(t.input_schema, ensure_ascii=False, indent=1)[:2000])


asyncio.run(main())
