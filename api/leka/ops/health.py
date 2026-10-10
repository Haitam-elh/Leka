"""How LEKA stands, component by component (LEKA-408): the API's backing
services, the object store, the worker, the scheduler, the queues, the
circuit breakers — each ok, degraded or down, said why.

`/api/v1/health` stays what a load balancer asks — can this API serve —
and this is what an operator asks: is the whole of LEKA working.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from leka.ops.alerts import queue_backlog, scheduler_stopped, worker_stalled
from leka.ops.metrics import circuits
from leka.ops.snapshot import Snapshot
from leka.platform import check_backing_services, object_store

PROBE_SECONDS = 3.0


@dataclass(frozen=True)
class Component:
    name: str
    status: str  # ok · degraded · down
    detail: str | None = None


async def _object_store() -> Component:
    try:
        await asyncio.wait_for(object_store().exists("leka-ops-probe"), PROBE_SECONDS)
    except Exception as error:
        return Component("object_store", "down", type(error).__name__)
    return Component("object_store", "ok")


async def components(snap: Snapshot) -> list[Component]:
    services = await check_backing_services()
    found = [Component(name, "ok" if up else "down") for name, up in sorted(services.items())]
    found.append(await _object_store())
    worker = worker_stalled(snap)
    found.append(Component("worker", "down" if worker else "ok", worker))
    scheduler = scheduler_stopped(snap)
    found.append(Component("scheduler", "down" if scheduler else "ok", scheduler))
    backlog = queue_backlog(snap)
    found.append(Component("queues", "degraded" if backlog else "ok", backlog))
    opened = sorted(k for k, n in circuits(snap).items() if n)
    found.append(
        Component(
            "dependencies",
            "degraded" if opened else "ok",
            f"circuit open: {', '.join(opened)}" if opened else None,
        )
    )
    if snap.unreadable:
        found.append(Component("state", "degraded", f"unreadable: {', '.join(snap.unreadable)}"))
    return found


def overall(found: list[Component]) -> str:
    """Down if a component the system cannot work without is; degraded if
    any is not ok."""
    critical = {"database", "redis", "worker", "scheduler"}
    if any(c.status == "down" and c.name in critical for c in found):
        return "down"
    return "ok" if all(c.status == "ok" for c in found) else "degraded"
