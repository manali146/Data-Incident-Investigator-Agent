import asyncio
import sys
from typing import Annotated, TypedDict

import yaml
from dotenv import load_dotenv
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool, ToolException
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()  # reads OPENAI_API_KEY from .env

MODEL = "gpt-4.1-mini"
MAX_TURNS = 10
CASES_FILE = "src/incidents/cases.yaml"

SYSTEM_PROMPT = """You are a data incident investigator for a DuckDB warehouse. Today is 1998-08-02.

Data model: orders (one row per order) -> lineitem (many rows per order, joined on l_orderkey = o_orderkey).
customer -> nation -> region gives each order its region. daily_revenue is a view over orders.

Procedure:
1. List tables and columns first. Never guess names.
2. Compare the affected period with a baseline (e.g. the previous 7 days).
3. Run health checks: missing days, duplicate keys, NULLs, value ranges, orphan rows between orders and lineitem.
4. For every anomaly a check finds, explain whether it relates to the alert and what it implies.
   Never dismiss a finding without saying why.
5. Decide explicitly: data bug or real business change. Compare the change with normal variation.

End with: Root cause, Evidence (with numbers), Verdict (data bug / real business change), Confidence (and why)."""

BUDGET_PROMPT = "You are out of tool calls. Give your final answer now from what you have, and say what is missing."


# --- MCP tools -> LangChain tools ---
def to_langchain_tool(session: ClientSession, mcp_tool) -> StructuredTool:
    async def call(**kwargs) -> str:
        result = await session.call_tool(mcp_tool.name, kwargs)
        text = result.content[0].text
        if result.is_error:
            raise ToolException(text)  # ToolNode turns this into a message the model can read
        return text

    return StructuredTool(
        name=mcp_tool.name,
        description=mcp_tool.description or "",
        args_schema=mcp_tool.input_schema,  # the MCP JSON schema, used as-is
        coroutine=call,
    )


# --- State: what flows between nodes -------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # add_messages appends instead of overwriting
    steps: int


# --- Graph: agent <-> tools, with a turn budget ---------------------------
def build_graph(model, tools):
    model_with_tools = model.bind_tools(tools)

    def agent(state: AgentState) -> dict:
        steps = state["steps"]
        messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        if steps >= MAX_TURNS:
            # Out of budget: ask for a final answer, with no tools available
            response = model.invoke([*messages, SystemMessage(BUDGET_PROMPT)])
        else:
            response = model_with_tools.invoke(messages)
        return {"messages": [response], "steps": steps + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if last.tool_calls and state["steps"] <= MAX_TURNS:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


# --- Run one case from cases.yaml -----------------------------------------
def load_case(case_id: str) -> dict:
    with open(CASES_FILE) as f:
        cases = {c["id"]: c for c in yaml.safe_load(f)}
    return cases[case_id]


async def investigate(case_id: str, model=None) -> str:
    case = load_case(case_id)
    server = StdioServerParameters(
        command="mcp-server-motherduck", args=["--db-path", case["db"]]
    )
    print(f"Case: {case_id}\nAlert: {case['alert']}")

    # The MCP session must stay open while the graph runs, so everything lives inside it
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = await session.list_tools()
            tools = [to_langchain_tool(session, t) for t in mcp_tools.tools]

            app = build_graph(model or ChatOpenAI(model=MODEL), tools)
            state = {"messages": [HumanMessage(case["alert"])], "steps": 0}

            # Stream node by node so we can watch the agent think
            answer = ""
            async for update in app.astream(state, stream_mode="updates"):
                for node, output in update.items():
                    last = output["messages"][-1]
                    if node == "agent" and last.tool_calls:
                        for tc in last.tool_calls:
                            print(f"\n[step {output['steps']}] {tc['name']}({tc['args']})")
                    elif node == "tools":
                        for msg in output["messages"]:
                            print(f"  -> {str(msg.content)[:200]}")
                    else:
                        answer = last.content

    print(f"\n=== Final answer ===\n{answer}")
    return answer


if __name__ == "__main__":
    asyncio.run(investigate(sys.argv[1] if len(sys.argv) > 1 else "duplicate_load"))

# uv run src/data_incident_investigator_agent/graph.py missing_day
# uv run src/data_incident_investigator_agent/graph.py real_drop