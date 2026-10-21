# Data-Incident-Investigator-Agent

Data teams lose hours on "is this metric drop real or a pipeline bug?" tickets. I built an agent that investigates them. It queries the warehouse through an MCP server, in read-only mode with row limits, and writes a root-cause report. I planted 8 incidents with known causes to measure it. Traces in Langfuse showed that it often [the failure found], so I [the fix], which took root-cause accuracy from X% to Y% at Z cents per investigation.
