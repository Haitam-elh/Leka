"""HTTP layer: one router file per module, assembled here.

Routes validate, call a single service, and return (architecture rule 6).
They hold no business logic and no database queries.

Module routers are added as the modules land; this file is the only place
that decides what is exposed over HTTP.
"""

from fastapi import APIRouter

from leka.api import health

api_router = APIRouter()
api_router.include_router(health.router)

__all__ = ["api_router"]
