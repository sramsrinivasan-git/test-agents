"""FastAPI scaffolding shared by agent HTTP entrypoints.

An agent's server module builds its app with `build_app`, attaches its
own request/response models and routes, and starts it with `serve`.
The generic bits live here: the app object, a `/healthz` probe, the
run-id minter, and the uvicorn launcher.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI


def build_app(title: str) -> FastAPI:
    """Create a FastAPI app with a `/healthz` probe already wired.

    The caller attaches its own routes to the returned app.
    """
    app = FastAPI(title=title)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def new_run_id(prefix: str) -> str:
    """Mint a unique, sortable run id, e.g. `audit-2026-06-15T12:00:00Z-a1b2c3`."""
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"


def serve(app: FastAPI, *, default_port: int = 8080) -> None:
    """Run the app under uvicorn, honoring the PORT env var (GKE convention)."""
    import uvicorn

    port = int(os.environ.get("PORT", str(default_port)))
    uvicorn.run(app, host="0.0.0.0", port=port)
