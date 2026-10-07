"""A stdio MCP adapter that never opens the database or starts the service."""
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .server import INSTRUCTIONS


async def bridge(directory, url):
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=30.0)) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as upstream:
                await upstream.initialize()
                tools = (await upstream.list_tools()).tools
                server = Server("handoff", version="0.1.0", instructions=INSTRUCTIONS)

                @server.list_tools()
                async def list_tools():
                    return tools

                @server.call_tool(validate_input=False)
                async def call_tool(name, arguments):
                    return await upstream.call_tool(name, arguments or {})

                async with stdio_server() as (incoming, outgoing):
                    await server.run(incoming, outgoing, server.create_initialization_options())
