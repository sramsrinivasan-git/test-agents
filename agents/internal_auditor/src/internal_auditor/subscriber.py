"""Pub/Sub entrypoint for the GKE deployment.

Subscribes to PUBSUB_TRIGGER_SUBSCRIPTION and runs the orchestrator
once per message. The message body is the audit trigger:

    {"trigger_type": "scheduled" | "on_demand", "lookback_hours": 1.0}

Per message:
  1. Parse the trigger envelope.
  2. Mint a run_id.
  3. Build the orchestrator prompt and run root_agent via common.runner.
  4. Log a single structured line with {run_id, response}.
  5. Ack on success; nack on any exception (Pub/Sub retries per the
     subscription's retry policy / hands to DLQ if configured).

There is no synchronous result delivery. Callers retrieve the audit
output from Cloud Logging (filter by run_id) or, later, from BQ /
Firestore once the Policy Agent lands. `trigger_type` is provenance
only - "scheduled" means a Cloud Scheduler cron published the message,
"on_demand" means a human / system published ad-hoc.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from common.ids import new_run_id
from common.pubsub import run_subscriber
from common.runner import run_agent

from internal_auditor.agent import root_agent
from internal_auditor.config import APP_NAME


logger = logging.getLogger(__name__)


def _handle(payload: dict) -> str:
    """Run one audit per Pub/Sub message; return the run_id."""
    trigger_type = payload.get("trigger_type", "scheduled")
    lookback_hours = float(payload.get("lookback_hours", 1.0))
    run_id = new_run_id("audit")
    prompt = (
        f"trigger_type={trigger_type} lookback_hours={lookback_hours} "
        f"run_id={run_id}\nRun the audit per your instructions."
    )
    response = asyncio.run(
        run_agent(root_agent, prompt, app_name=APP_NAME, user_id="trigger")
    )
    # One structured log line per audit; downstream consumers query
    # Cloud Logging by `jsonPayload.run_id` until BQ/Firestore writes land.
    logger.info(json.dumps({"run_id": run_id, "response": response}))
    return run_id


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    subscription_id = os.environ["PUBSUB_TRIGGER_SUBSCRIPTION"]
    max_concurrent = int(os.environ.get("PUBSUB_MAX_CONCURRENT", "1"))
    run_subscriber(
        project_id=project_id,
        subscription_id=subscription_id,
        handler=_handle,
        max_concurrent=max_concurrent,
    )


if __name__ == "__main__":
    main()
