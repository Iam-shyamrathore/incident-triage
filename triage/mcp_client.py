import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import ROOT


@asynccontextmanager
async def connect():
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "triage.replay_mcp"],
        cwd=ROOT,
    )
    async with (
        stdio_client(server) as (reads, writes),
        ClientSession(
            reads, writes, read_timeout_seconds=timedelta(seconds=6)
        ) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        tools = {
            tool.name: {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.inputSchema,
            }
            for tool in listed.tools
        }
        yield ReplayTools(session, tools)


class ReplayTools:
    def __init__(self, session, definitions):
        self.session = session
        self.definitions = definitions

    async def call(self, tool, arguments):
        validate(arguments, self.definitions[tool]["schema"])
        result = await self.session.call_tool(tool, arguments=arguments)
        if result.isError or not isinstance(result.structuredContent, dict):
            raise RuntimeError("MCP returned an error for the selected diagnostic")
        return result.structuredContent
