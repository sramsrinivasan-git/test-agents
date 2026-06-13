"""Orchestrator agent (root) for the Internal Auditor POC.

Receives audit triggers, calls specialist agents as tools, returns
merged findings. In this POC the available specialists are
`log_analyzer` and `asset_inspector`.

trigger_type is provenance only ("scheduled" = Cloud Scheduler cron,
"on_demand" = ad-hoc API call). Both run the same workflow; the field
is carried through to the output so downstream consumers (BQ, dashboards)
can tell scheduled audits from on-demand ones.

Out of scope on purpose (deferred to later phases per plan.md):
- Agent Behavior Evaluator.
- Policy Evaluator - the agent that decides violation vs clean.
- Alert Dispatcher (Pub/Sub).
- BigQuery / Firestore writes. Those happen only AFTER a verified
  violation; with no Policy Agent yet, there is nothing to write.
- ReAct scratchpad / replan loop. Will land with the Policy Agent.

Why AgentTool, not sub_agents:
The orchestrator is a coordinator, not a router. It needs to call
specialists in parallel, get structured returns, merge them, and
potentially re-invoke during a replan. `AgentTool` keeps the
orchestrator in control of the conversation and lets its LLM fan out
to log_analyzer + asset_inspector in a single turn. `sub_agents` would
transfer control away and serialize the calls.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from internal_auditor.asset_inspector import asset_inspector_agent
from internal_auditor.config import GEMINI_MODEL
from internal_auditor.log_analyzer import log_analyzer_agent

ORCHESTRATOR_INSTRUCTION = """\
You are the Internal Auditor Orchestrator. You are the root agent and
you remain in control of the conversation throughout the run.

Inputs you receive from the trigger:
- trigger_type:   "scheduled" | "on_demand"   (provenance only)
- lookback_hours: float                       (the audit window)
- run_id:         string                      (generated upstream)

`trigger_type` records HOW the run was kicked off (Cloud Scheduler
cron vs ad-hoc API call). It does NOT change what you do - the audit
workflow is identical either way. Carry it through to the output so
downstream consumers can tell scheduled audits from on-demand ones.

Workflow (same for both trigger types):
1. In a single turn, call BOTH specialist tools in parallel:
   - `log_analyzer`     - pass a JSON brief describing the time window
                          (lookback hours, window_end if provided) and
                          any service / method / principal filters.
   - `asset_inspector`  - pass a JSON brief describing the snapshot
                          anchor (window_end), and any resource_type /
                          project / role / member filters.
   Issue both tool calls together so they run concurrently. Wait for
   both returns.
2. Merge the two structured findings into a single JSON object:
   {
     "run_id": "<run_id from input>",
     "trigger_type": "<scheduled|on_demand from input, verbatim>",
     "lookback_hours": <float>,
     "findings": {
       "log_analyzer":    <whatever log_analyzer returned, verbatim>,
       "asset_inspector": <whatever asset_inspector returned, verbatim>
     },
     "next_step": "policy_evaluation_pending"
   }
3. Stop. Do not classify anything as a violation. Do not write to
   BigQuery, Firestore, or anywhere else. The Policy Agent (future
   phase) consumes this output and gates any storage writes.

Never invent findings. If a tool returns zero entries, surface that
honestly in the JSON. If a tool errors, include the error string in
its slot of `findings` and continue - never fail the whole run because
one specialist failed.
"""


root_agent = LlmAgent(
    name="orchestrator",
    model=GEMINI_MODEL,
    description=(
        "Internal Auditor root agent. Receives audit triggers and calls "
        "specialist agents (log_analyzer, asset_inspector) as tools in "
        "parallel."
    ),
    instruction=ORCHESTRATOR_INSTRUCTION,
    tools=[
        AgentTool(agent=log_analyzer_agent),
        AgentTool(agent=asset_inspector_agent),
    ],
)
