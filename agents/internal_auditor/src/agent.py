"""Orchestrator agent (root) for the Internal Auditor POC.

Receives audit triggers, delegates to sub-agents, returns merged
findings. In this POC the only sub-agent is `log_analyzer`.

Out of scope on purpose (deferred to later phases per plan.md):
- Asset Inspector sub-agent (Cloud Asset MCP server).
- Agent Behavior Evaluator (real-time path).
- Policy Evaluator - the agent that decides violation vs clean.
- Alert Dispatcher (Pub/Sub).
- BigQuery / Firestore writes. Those happen only AFTER a verified
  violation; with no Policy Agent yet, there is nothing to write.
- ReAct scratchpad / replan loop. Will land with the Policy Agent.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from internal_auditor.config import GEMINI_MODEL
from internal_auditor.log_analyzer import log_analyzer_agent

ORCHESTRATOR_INSTRUCTION = """\
You are the Internal Auditor Orchestrator. You are the root agent.

Inputs you receive from the trigger:
- trigger_type: "batch" | "realtime"
- lookback_hours: float (batch only)
- run_id: string (generated upstream)

For trigger_type == "batch":
1. Delegate to the `log_analyzer` sub-agent. Tell it the time window
   (the lookback in hours) and any filters the caller provided. Ask it
   to return its standard findings JSON.
2. When it returns, package the response as a single JSON object:
   {
     "run_id": "<run_id from input>",
     "trigger_type": "batch",
     "lookback_hours": <float>,
     "findings": {
       "log_analyzer": <whatever the sub-agent returned, verbatim>
     },
     "next_step": "policy_evaluation_pending"
   }
3. Stop. Do not classify anything as a violation. Do not write to
   BigQuery, Firestore, or anywhere else. The Policy Agent (future
   phase) consumes this output and gates any storage writes.

For trigger_type == "realtime" (or anything else): respond with
  { "status": "not_implemented",
    "reason": "Real-time path is not in scope for the POC." }

Never invent findings. If the sub-agent returns zero entries, surface
that honestly in the JSON.
"""


root_agent = LlmAgent(
    name="orchestrator",
    model=GEMINI_MODEL,
    description=(
        "Internal Auditor root agent. Receives audit triggers and "
        "delegates to sub-agents (currently: log_analyzer)."
    ),
    instruction=ORCHESTRATOR_INSTRUCTION,
    sub_agents=[log_analyzer_agent],
)
