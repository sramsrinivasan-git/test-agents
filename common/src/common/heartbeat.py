"""Liveness heartbeat for non-HTTP services.

Pub/Sub subscribers don't speak HTTP, so a FastAPI `/healthz` doesn't
fit. Instead, each agent calls `tick()` whenever it makes progress
(per message + on a periodic backstop); Kubernetes runs an `exec`
liveness probe that checks the file's mtime is recent.

Why a file instead of a TCP listener: we want the probe to detect a
*deadlocked subscriber*, not just a live process. A TCP probe would
pass even if the work loop was wedged; a stale heartbeat file proves
the loop has stopped advancing.

The matching k8s probe lives in each agent's Deployment manifest, e.g.

    livenessProbe:
      exec:
        command:
          - /bin/sh
          - -c
          - 'test -f /tmp/alive && test $(($(date +%s) - $(stat -c %Y /tmp/alive))) -lt 90'
      initialDelaySeconds: 30
      periodSeconds: 30
"""

from __future__ import annotations

import os

HEARTBEAT_PATH = "/tmp/alive"


def tick(path: str = HEARTBEAT_PATH) -> None:
    """Touch the heartbeat file (creating it if missing)."""
    try:
        os.utime(path, None)
    except FileNotFoundError:
        # Create the file; mtime is set automatically.
        with open(path, "w"):
            pass
