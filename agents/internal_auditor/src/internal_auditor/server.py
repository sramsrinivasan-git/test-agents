"""HTTP entrypoint for the GKE deployment.

Exposes:
  POST /audit    {"trigger_type": "scheduled", "lookback_hours": 1.0}
                 -> {"run_id": ..., "response": "<orchestrator JSON>"}
  GET  /healthz  -> {"status": "ok"}   (provided by common.serving)

`trigger_type` is provenance only - "scheduled" means a Cloud Scheduler
cron fired this run, "on_demand" means a human / system called the API
ad-hoc. The agent workflow is identical for both.

Only the audit-specific contract (request/response shape, the /audit
route, the prompt) lives here; the FastAPI app, /healthz, run-id minting,
and the ADK run loop come from common.serving / common.runner.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from common.runner import run_agent
from common.serving import build_app, new_run_id, serve

from internal_auditor.agent import root_agent
from internal_auditor.config import APP_NAME


TriggerType = Literal["scheduled", "on_demand"]


class AuditRequest(BaseModel):
    trigger_type: TriggerType = Field(
        default="on_demand",
        description="How the run was kicked off; provenance only.",
    )
    lookback_hours: float = Field(default=1.0, ge=0)


class AuditResponse(BaseModel):
    run_id: str
    response: str


app = build_app("Internal Auditor")


@app.post("/audit", response_model=AuditResponse)
async def trigger_audit(req: AuditRequest) -> AuditResponse:
    run_id = new_run_id("audit")
    prompt = (
        f"trigger_type={req.trigger_type} lookback_hours={req.lookback_hours} "
        f"run_id={run_id}\nRun the audit per your instructions."
    )
    response = await run_agent(
        root_agent, prompt, app_name=APP_NAME, user_id="trigger"
    )
    return AuditResponse(run_id=run_id, response=response)


def main() -> None:
    serve(app)


if __name__ == "__main__":
    main()
