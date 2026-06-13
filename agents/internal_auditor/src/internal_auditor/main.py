"""CLI entry point.

Runs a single batch audit and prints the orchestrator's final response.
Intended for local development / smoke testing - production triggers go
through the HTTP server in `internal_auditor.server`.

Usage:
    internal-auditor --lookback-hours 1
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timezone

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from internal_auditor.agent import root_agent
from internal_auditor.config import APP_NAME


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return f"audit-{stamp}-{uuid.uuid4().hex[:6]}"


async def run_batch_audit(lookback_hours: float) -> None:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id="local-cli",
    )
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )
    run_id = _new_run_id()
    prompt_text = (
        f"trigger_type=batch lookback_hours={lookback_hours} run_id={run_id}\n"
        f"Run the batch audit per your instructions."
    )
    new_message = types.Content(
        role="user", parts=[types.Part.from_text(text=prompt_text)]
    )
    async for event in runner.run_async(
        user_id="local-cli",
        session_id=session.id,
        new_message=new_message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text = event.content.parts[0].text or ""
            print(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a single Internal Auditor batch audit and print the result."
    )
    parser.add_argument(
        "--lookback-hours",
        type=float,
        default=1.0,
        help="How far back the log analyzer should look (default: 1.0).",
    )
    args = parser.parse_args()
    asyncio.run(run_batch_audit(args.lookback_hours))


if __name__ == "__main__":
    main()
