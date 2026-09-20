"""FastAPI application entry point.

    uvicorn leka.main:app --reload

Importing this module reads the environment (leka.core.config) and therefore
fails immediately if it is incomplete.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from leka.api import api_router
from leka.core.config import settings
from leka.core.logging import configure_logging
from leka.db import engine
from leka.identity import configure_identity
from leka.identity.csrf import csrf_middleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging on the way up, close the pool on the way down."""
    configure_logging(settings)
    logger.info("leka_starting", environment=settings.environment)
    yield
    await engine.dispose()
    logger.info("leka_stopped")


app = FastAPI(
    title="LEKA API",
    version="0.1.0",
    description="Continuous architecture mapping and evidence-backed answers.",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url=f"{settings.api_v1_prefix}/docs",
    lifespan=lifespan,
)

# Defence in depth behind SameSite=Lax. Middleware rather than a dependency
# on each route, so a route added later is covered without its author knowing
# the check exists. See docs/adr/009-cookie-strategy.md.
app.middleware("http")(csrf_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# Fill the seam LEKA-331 left open. Until this call, every route needing a
# user raises — which is what kept the platform honest while identity was
# unimplemented. Tests replace these overrides with their own.
configure_identity(app)
