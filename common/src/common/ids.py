"""ID minting helpers shared by agents."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_run_id(prefix: str) -> str:
    """Mint a unique, sortable run id, e.g. `audit-2026-06-15T12:00:00Z-a1b2c3`."""
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"
