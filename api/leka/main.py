"""FastAPI application entry point.

    uvicorn leka.main:app --reload

Importing this module reads the environment (leka.core.config) and therefore
fails immediately if it is incomplete.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from leka.api import api_router
from leka.api.errors import ERROR_RESPONSES, register_error_handlers
from leka.api.ops import metrics_middleware, watch_forever
from leka.api.ratelimit import rate_limit_middleware
from leka.api.request_id import REQUEST_ID_HEADER, request_id_middleware
from leka.capabilities import sync_catalogue
from leka.core.config import settings
from leka.core.logging import configure_logging
from leka.db import engine
from leka.identity import configure_identity
from leka.identity.csrf import csrf_middleware
from leka.platform.monitoring import configure_monitoring

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging on the way up, close the pool on the way down."""
    configure_logging(settings)
    # After logging, never before: the Sentry integration scrubs its events
    # with the masker that configure_logging builds, and with no masker it
    # would report the first errors unscrubbed.
    monitoring = configure_monitoring(settings)
    logger.info("leka_starting", environment=settings.environment, monitoring=monitoring)
    # A warning, never a refusal: stopping because a key is a day past its
    # lifetime would be manufacturing an outage. See core/settings/_rotation.py.
    for overdue in settings.overdue_secrets(datetime.now(UTC).date()):
        logger.warning("secret_rotation_overdue", **overdue._asdict())
    # What LEKA can do, registered — every version, every move of its
    # lifecycle (LEKA-393). Never in the way of starting: the hourly sync
    # registers what this one could not.
    try:
        await sync_catalogue()
    except Exception:
        logger.exception("capability_catalogue_sync_failed")
    # The operational alerts, judged here too (LEKA-408): the worker that
    # judges them may be what is down.
    watching = (
        asyncio.create_task(watch_forever(settings.ops_watch_interval_seconds))
        if settings.ops_watch_interval_seconds
        else None
    )
    yield
    if watching is not None:
        watching.cancel()
    await engine.dispose()
    logger.info("leka_stopped")


# The interactive documentation and the schema, served over HTTP — or not.
#
# On a B2B SaaS, /docs published to anyone who asks is a free map of the
# attack surface: every route, every field, every enumeration, kept up to
# date by us. It stays open everywhere except production.
#
# The schema is still GENERATED in production — app.openapi() works
# regardless, and CI keeps checking api-types.ts for drift. What changes is
# who can fetch it over the network, not whether it exists.
_PUBLISH_SCHEMA = not settings.is_production

app = FastAPI(
    title="LEKA API",
    version="0.1.0",
    description="Continuous architecture mapping and evidence-backed answers.",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json" if _PUBLISH_SCHEMA else None,
    docs_url=f"{settings.api_v1_prefix}/docs" if _PUBLISH_SCHEMA else None,
    redoc_url=f"{settings.api_v1_prefix}/redoc" if _PUBLISH_SCHEMA else None,
    lifespan=lifespan,
)

# Three handlers, so a client meets one error shape instead of three. See
# leka/api/errors.py for what FastAPI does without them.
register_error_handlers(app)

# Defence in depth behind SameSite=Lax. Middleware rather than a dependency
# on each route, so a route added later is covered without its author knowing
# the check exists. See docs/adr/009-cookie-strategy.md.
app.middleware("http")(csrf_middleware)

# A backstop limit on every route, so one is never missing because an
# author forgot to ask for it. The authentication routes keep their own,
# stricter ones on top. See leka/api/ratelimit.py.
app.middleware("http")(rate_limit_middleware)

# Added LAST, which puts it OUTERMOST: Starlette runs the most recently
# added middleware first. Everything below it — a CSRF refusal, a rate
# limit refusal, an unparseable body — therefore carries an identifier,
# and those are exactly the refusals somebody will ask about.
app.middleware("http")(request_id_middleware)

# Every request counted for the metrics (LEKA-408) — outside the request id,
# the rate limit and CSRF, so their refusals are counted too. CORS, added
# after, is outside it: a preflight the browser sends is not counted.
app.middleware("http")(metrics_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser can see the header and JavaScript cannot.
    # The whole point is that a user can read us the id from a failure.
    expose_headers=[REQUEST_ID_HEADER],
)

# ERROR_RESPONSES on every route, so the published schema describes the shape
# errors actually have. Without it api-types.ts types FastAPI's default —
# and a frontend would be written against a body that never arrives.
app.include_router(api_router, prefix=settings.api_v1_prefix, responses=ERROR_RESPONSES)

# Fill the seam LEKA-331 left open. Until this call, every route needing a
# user raises — which is what kept the platform honest while identity was
# unimplemented. Tests replace these overrides with their own.
configure_identity(app)
