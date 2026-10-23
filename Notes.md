1. Why use an agent here instead of a fixed set of diagnostic SQL checks? When would the fixed checks win?
2. What does MCP give you over writing the tools directly in your code? What does it cost?
3. How does your loop stop, and what happens when it hits the step budget?
4. What exactly is in a span, and how would you find the most expensive step across 1,000 runs?
5. How did you grade the answers, and how do you know your LLM judge is right? Compare it with your own labels on 20 cases.
6. How would a malicious row in the data attack your agent, and what stops it?
7. What would you change to run this in production on Snowflake? Think about auth, cost limits, caching, and alerting on failed investigations. This one links back to your existing production LLM monitoring story.

EUROPE is at 0.51, which we planted, but ASIA is at 0.70 with no incident at all. Normal week-to-week noise is around ±30%. So the agent can’t just say “down 50%, so it’s a bug”. It has to compare against normal variation and run the health checks.

8. What does MCP give you compared with calling duckdb.connect() directly?
“MCP decouples the agent from its tools (the agent doesn’t need to know how DuckDB works; it just asks a middleman). With duckdb.connect(), I’d hard-code the database client, write my own tool schemas and permission checks, and redo all of it for every new data source. With MCP, the server advertises its tools at runtime via tools/list, with JSON schemas the LLM can read (it hands the model a menu with instructions for each dish). So adding Snowflake or GitHub later is a config change, not a code change (plug in a new middleman, and the agent stays the same).
It also gives me a security boundary (the dangerous stuff lives behind a door I control). The server runs read-only, caps rows and characters, and labels tools with hints like readOnlyHint. So even if the model hallucinates a DELETE or gets prompt-injected, the guardrail is enforced in the server, not in the prompt (a polite ‘please don’t delete’ in the prompt can be ignored; a locked door can’t). And because it’s a standard protocol, the same server works with any MCP host: Claude Desktop, Cursor, or LangGraph agent (write once, plug in anywhere).”
Short version, if they want one line: “MCP turns tools into plug-and-play, self-describing services with a permission boundary, so the agent isn’t hard-wired to the database.”

Who’s who (the 3 MCP roles):
---------------------------------------------------------------------------------------------------------------------------
Role	What it is	In your project
---------------------------------------------------------------------------------------------------------------------------
Host	The app the user runs. It owns the LLM, decides which servers to connect to, and enforces user permissions	
        Right now mcp_hello.py (with no LLM yet). From M3, your agent app. Claude Desktop and Cursor are examples of hosts
---------------------------------------------------------------------------------------------------------------------------
Client	The connector inside the host. There’s one client per server, and it speaks the protocol	
        The ClientSession object in your script
---------------------------------------------------------------------------------------------------------------------------
Server	Exposes tools, resources and prompts, and does the real work	
        The mcp-server-motherduck process, which holds the DuckDB connection
---------------------------------------------------------------------------------------------------------------------------

# uv run .\src\data_incident_investigator_agent\agent_loop.py
Red Flags for Model= 'gpt-4.1-mini' and thin prompt:
1. 2 of 6 turns were wasted guessing the schema. At scale, that’s cost and latency for nothing.
2. The evidence is thin. “No rows for today” is just the symptom restated. It never compared against a baseline (about 60 orders a day before), and it never checked whether sales actually happened. Here’s the killer clue it missed: the lineitem rows for today’s orders still exist. You only deleted from orders. Line items pointing at missing orders prove the sales happened and the orders load failed.
3. “Confidence: High” is unjustified. It says “sales did not stop”, but nothing it ran proves that.

![alt text](image.png)

Auto-instrumentation: a library hooks into LangChain and LangGraph and creates spans for everything, with no extra code: every graph node, every LLM call with the full prompt and response, every tool call with its inputs and outputs. It’s 2 lines:


# in tracing.py, at the end of setup_tracing(), before the return
from openinference.instrumentation.langchain import LangChainInstrumentor
LangChainInstrumentor().instrument(tracer_provider=provider)

Your CSV shows why this matters: the input and output columns are empty for every span. Your manual spans record that the LLM was called and how many tokens it used, but not what it was told or what it said. Auto-instrumentation fills those in, so in Langfuse you can click an LLM call and read the exact messages.

What to compare after one run with both turned on:

	Manual	Auto (OpenInference)
Effort	You write every span	2 lines
Prompt and response text	❌	✅
Business context (case, SQL, verdict)	✅	❌ (generic names)
Noise	Low	High (many small internal spans)

You’ll also see each LLM call twice: once as your llm span and once as the auto ChatOpenAI span. That’s expected.

What most teams do, and a good interview answer: “Both. Auto-instrumentation for the framework internals (prompts, responses, node timings), and manual spans for business context the framework can’t know about, like which incident, which SQL, and whether it errored. I dropped my manual LLM span because the auto one carried strictly more.”

1st Iteration Evals:
Failures 1 to 3: “Data bug, not a real business change” was graded as business change because of the substring order. That’s a grader bug.
Failure 4: the agent wrote “Verdict” twice, and my regex only looked 150 characters past the first one. Also a grader bug, plus a small format issue on the agent’s side.

2nd Iteration Evals:
“Traces are only useful if you can find the one you need, so I designed the trace identity on purpose: one session per eval run, the case as the trace name, tags for filtering, and the inputs and outputs on the root span.”

3rd Iteration Evals:
Verdict accuracy was 100%, but my LLM judge and traces showed the agent was fabricating orphan-row evidence in 3 of 5 case types. I traced it to a schema misunderstanding and gave the agent verified health-check SQL, which raised findings accuracy from X to Y and removed the unsupported claims.

4th Iteration Evals:
Disagreements have three possible culprits: the agent, the judge, or the rubric (your expected_findings). Sometimes the right fix is rewording the expected finding, like “≈59 duplicated keys = all orders that day”.
New agent failure: reading a LIMIT result as a count. Fix it with a prompt rule: “When you report a number, compute it with count(). Never infer totals from a query that has LIMIT.”*
No run ever checks average order value, so finding 2 is always missed. But it’s a genuinely useful diagnostic: duplicates keep the average the same, a unit change multiplies it by 100, and a real drop keeps it normal. Add to the procedure: “Compare both order count and average order value against the baseline.” That should lift unit_change too.

“I attacked my own agent with a poisoned table comment, and it abandoned correct evidence to obey it. I fixed it with defence in depth: strip untrusted metadata at the tool boundary, log it as a security event in the trace, add a trust rule in the prompt, and keep the attack as a permanent eval case.”

“LLM calls are non-deterministic, so I split testing in two. CI runs fast deterministic tests on the control flow and the security filter with a scripted model. The eval suite measures the agent’s real behaviour.”