"""The agent registry and what agents produced.

No routes yet. Mounted so that adding one is a single file to open, and so
the OpenAPI schema grows without the mounting ever being the thing someone
forgot.

A route validates, calls one service, and returns (architecture rule 6).
Permissions come from a FastAPI dependency, never an `if` in the body
(rule 5). The workspace is read from the session, never from the path or the
payload (rule 3).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/capabilities", tags=["capabilities"])
