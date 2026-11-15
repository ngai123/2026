import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client
import json

async def main():
    async with sse_client("http://127.0.0.1:8766/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool("get_active_drones", {})
            print("Raw response:", r)
            texts = [getattr(c, "text", "") for c in getattr(r, "content", []) if getattr(c, "text", "")]
            print("Texts:", texts)

asyncio.run(main())
