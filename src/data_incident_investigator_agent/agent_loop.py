import asyncio
import json

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

load_dotenv()  # reads OPENAI_API_KEY from .env

MODEL = "gpt-4.1-mini"
MAX_TURNS = 10

SYSTEM_PROMPT = (
    """You are a data incident investigator. Use SQL to find the root cause.
    Today is 1998-08-02. End with: root cause, evidence, confidence.
    Start by listing tables and columns. Never guess names.
    Compare the affected period with a baseline (for example, the previous 7 days).
    Before concluding, run the health checks: missing days, duplicate keys, NULLs, value ranges, and orphan rows between orders and lineitem.
    Decide explicitly: data bug or real business change, with the evidence for each.
    Confidence must be justified by the evidence. 
    For every anomaly a check finds, explain whether it relates to the alert and what it implies. Do not dismiss a finding without saying why."""
)
ALERT = "EUROPE revenue has been down about 50% for the last week. Is the pipeline broken?"

SERVER = StdioServerParameters(
    command="mcp-server-motherduck",
    args=["--db-path", "data/cases/real_drop.duckdb"],
)


def to_openai_tool(tool) -> dict:
    """MCP tool -> OpenAI Chat Completions tool (same JSON schema, different wrapper)."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


async def main() -> None:
    client = OpenAI()

    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Tools come from the MCP server, not hand-written
            mcp_tools = await session.list_tools()
            tools = [to_openai_tool(t) for t in mcp_tools.tools]

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": ALERT},
            ]

            # The ReAct loop: think -> act (tool) -> observe (result) -> repeat
            for turn in range(1, MAX_TURNS + 1):
                response = client.chat.completions.create(
                    model=MODEL, messages=messages, tools=tools
                )
                msg = response.choices[0].message
                messages.append(msg)

                # No tool calls means the model is giving its final answer
                if not msg.tool_calls:
                    print(f"\n=== Final answer (turn {turn}) ===\n{msg.content}")
                    break

                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    print(f"\n[turn {turn}] {tc.function.name}({args})")

                    result = await session.call_tool(tc.function.name, args)
                    text = result.content[0].text
                    print(text[:500])  # keep the console readable

                    # One tool message per call, linked by tool_call_id
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
            else:
                print(f"Stopped after {MAX_TURNS} turns without a final answer.")


asyncio.run(main())