"""Pub/Sub subscriber loop shared by agent entrypoints.

Each agent's entrypoint defines a sync handler `(payload: dict) -> str`
and calls `run_subscriber(...)`. The loop pulls messages from the
configured subscription, dispatches each to the handler, acks on
success or nacks on exception (Pub/Sub will redeliver per the
subscription's retry policy), and ticks the heartbeat file so the
k8s liveness probe can detect a wedged subscriber.

`run_subscriber` blocks forever - it's meant to be the container's
main process.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

from google.cloud import pubsub_v1

from common.heartbeat import tick

logger = logging.getLogger(__name__)

# Handler is sync because the underlying Pub/Sub client invokes
# callbacks from a worker thread. If the agent needs async work
# (and ours does - the ADK runner is async), the handler can
# `asyncio.run(...)` internally; one-shot loops compose fine.
Handler = Callable[[dict], str]


def run_subscriber(
    *,
    project_id: str,
    subscription_id: str,
    handler: Handler,
    max_concurrent: int = 1,
    backstop_seconds: int = 15,
) -> None:
    """Pull from a Pub/Sub subscription, dispatch each message to `handler`.

    Args:
        project_id: GCP project that owns the subscription.
        subscription_id: Subscription name (NOT the full path).
        handler: Sync callable that takes the parsed JSON body and
            returns a result string (logged at INFO; downstream
            consumers should read it from Cloud Logging or from
            whatever store the handler writes to).
        max_concurrent: Pub/Sub flow-control - how many unacked
            messages the client may hold at once. 1 = strict serial.
        backstop_seconds: Heartbeat tick interval used when no
            messages flow. Pick something < the liveness probe's
            "stale after N seconds" threshold so an idle subscriber
            doesn't get restarted.
    """
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project_id, subscription_id)

    def _callback(message: pubsub_v1.subscriber.message.Message) -> None:
        tick()
        try:
            payload = json.loads(message.data.decode("utf-8"))
            result = handler(payload)
            logger.info("processed message: %s", result)
            message.ack()
        except Exception:
            logger.exception("handler failed; nacking")
            message.nack()
        finally:
            tick()

    flow_control = pubsub_v1.types.FlowControl(max_messages=max_concurrent)
    streaming_pull_future = subscriber.subscribe(
        subscription_path, callback=_callback, flow_control=flow_control
    )
    tick()
    logger.info("subscribed to %s (max_concurrent=%d)", subscription_path, max_concurrent)

    try:
        while True:
            time.sleep(backstop_seconds)
            tick()
    except KeyboardInterrupt:
        streaming_pull_future.cancel()
        streaming_pull_future.result(timeout=30)
