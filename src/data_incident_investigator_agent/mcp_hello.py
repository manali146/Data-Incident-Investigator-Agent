import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Which server to start, and on which incident database
SERVER = StdioServerParameters(
    command="mcp-server-motherduck",
    args=["--db-path", "data/cases/missing_day.duckdb"],
)


async def run_sql(session: ClientSession, sql: str) -> None:
    """Send one tools/call and print what came back."""
    result = await session.call_tool("execute_query", {"sql": sql})
    text = result.content[0].text
    print(f"\nSQL: {sql}")
    print(f"isError: {result.is_error}")                                            # was isError
    print(json.dumps(json.loads(text), indent=2) if not result.is_error else text)  # was isError


async def main() -> None:
    # 1. Start the server as a child process, talk to it over stdin/stdout
    async with stdio_client(SERVER) as (read, write):
        # 2. Wrap the raw pipes in an MCP session
        async with ClientSession(read, write) as session:
            # 3. Handshake: initialize + notifications/initialized
            init = await session.initialize()
            print(f"Connected to {init.server_info.name} {init.server_info.version}")   # was serverInfo
            
            # 4. tools/list: what can this server do?
            tools = await session.list_tools()
            for tool in tools.tools:
                args = list(tool.input_schema.get("properties", {}))    # was inputSchema
                print(f"- {tool.name}({', '.join(args)})")

            # 5. tools/call: ask a real question
            await run_sql(session, "SELECT max(o_orderdate) AS last_day FROM orders")

            # 6. Step 2c: try to break things (should be refused)
            await run_sql(session, "DELETE FROM orders")
    # 7. Leaving the `async with` blocks shuts the server down


asyncio.run(main())