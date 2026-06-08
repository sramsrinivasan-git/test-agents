"""HTTP entrypoint for the GKE deployment.

Exposes:
  POST /audit    {"trigger_type": "batch", "lookback_hours": 1.0}
                 -> {"run_id": ..., "response": "<orchestrator JSON>"}
  GET  /healthz  -> {"status": "ok"}

This is the surface the batch / real-time Cloud Functions call.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from internal_auditor.agent import root_agent
from internal_auditor.config import APP_NAME


class AuditRequest(BaseModel):
    trigger_type: str = Field(default="batch", description="batch | realtime")
    lookback_hours: float = Field(default=1.0, ge=0)


class AuditResponse(BaseModel):
    run_id: str
    response: str


_session_service = InMemorySessionService()
_runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    session_service=_session_service,
)

app = FastAPI(title="Internal Auditor")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/audit", response_model=AuditResponse)
async def trigger_audit(req: AuditRequest) -> AuditResponse:
    if req.trigger_type != "batch":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only trigger_type='batch' is implemented in this POC; "
                f"got {req.trigger_type!r}."
            ),
        )
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = f"audit-{stamp}-{uuid.uuid4().hex[:6]}"

    session = await _session_service.create_session(
        app_name=APP_NAME,
        user_id="trigger",
    )
    prompt_text = (
        f"trigger_type=batch lookback_hours={req.lookback_hours} "
        f"run_id={run_id}\nRun the batch audit per your instructions."
    )
    new_message = types.Content(
        role="user", parts=[types.Part.from_text(text=prompt_text)]
    )
    final_text = ""
    async for event in _runner.run_async(
        user_id="trigger",
        session_id=session.id,
        new_message=new_message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or ""
    return AuditResponse(run_id=run_id, response=final_text)


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
