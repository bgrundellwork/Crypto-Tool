# app/db/bootstrap.py
from __future__ import annotations

from app.db.migrations import enforce_integrity_constraints


async def ensure_db_primitives() -> None:
    """
    Apply integrity constraints/indexes idempotently at startup.
    """
    await enforce_integrity_constraints()
