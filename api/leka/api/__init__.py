"""HTTP layer: one router file per module, assembled here.

This file is the only place that decides what LEKA exposes over HTTP. A
module without a line here is a module the outside world cannot reach —
which is the intended default.

Routes validate, call a single service, and return (architecture rule 6).
They hold no business logic and no database queries.
"""

from fastapi import APIRouter

from leka.api import (
    background,
    capabilities,
    connectors,
    context,
    enrichment,
    governance,
    graph,
    health,
    identity,
    ingestion,
    intentions,
    knowledge,
    platform,
    resolution,
    webhooks,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(background.router)

# Ordered the way the system is layered, not alphabetically: someone reading
# this should see the shape of the product.
api_router.include_router(identity.router)
api_router.include_router(platform.router)
api_router.include_router(governance.router)
api_router.include_router(connectors.router)
api_router.include_router(ingestion.router)
# What the workspace's sources resolve to (LEKA-357), and what enrichment
# adds to it (LEKA-359).
api_router.include_router(resolution.router)
api_router.include_router(enrichment.router)
# What systems send, signed rather than signed in (LEKA-350).
api_router.include_router(webhooks.router)
api_router.include_router(knowledge.router)
# The graph explored: search, walks, paths, the landscapes (LEKA-369).
api_router.include_router(graph.router)
api_router.include_router(context.router)
api_router.include_router(capabilities.router)
api_router.include_router(intentions.router)

__all__ = ["api_router"]
