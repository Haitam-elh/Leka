"""What happened, with where it stands (2026-10-19): a deployment says
whether it succeeded — « why do deployments fail? » is checked against it."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import leka.schema  # noqa: F401 — every module provides its capabilities
from leka.capabilities.registry import catalogue
from leka.capabilities.tools import handlers
from leka.knowledge import EntityType
from leka.knowledge.models import Lifecycle
from leka.knowledge.schemas import EntityBrief

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
SERVICE, OK, FAILED = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _brief(entity: uuid.UUID, kind: EntityType, name: str) -> EntityBrief:
    return EntityBrief(id=entity, type=kind, key=name, name=name, lifecycle=Lifecycle.ACTIVE)


class Graph:
    async def briefs(self, ids: Any) -> dict[uuid.UUID, EntityBrief]:
        known = {
            SERVICE: _brief(SERVICE, EntityType.SERVICE, "Leka API"),
            OK: _brief(OK, EntityType.DEPLOYMENT, "main to production"),
            FAILED: _brief(FAILED, EntityType.DEPLOYMENT, "main to production"),
        }
        return {i: known[i] for i in ids if i in known}

    async def events(self, around: Any, **_: Any) -> list[tuple[uuid.UUID, datetime, str, None]]:
        return [
            (OK, NOW - timedelta(hours=1), "deployment", None),
            (FAILED, NOW - timedelta(hours=2), "deployment", None),
        ]

    async def states(self, ids: Any) -> dict[uuid.UUID, str]:
        return {OK: "succeeded", FAILED: "failed"}


async def test_what_happened_says_whether_each_deployment_succeeded() -> None:
    [debug] = [d for d in catalogue() if d.key == "debug-assistant"]
    happened = handlers(debug, Graph(), now=NOW)["what_happened"]  # type: ignore[arg-type]
    said = json.loads((await happened({"id": str(SERVICE), "days": 2})).text)
    assert [(e["id"], e["state"]) for e in said["events"]] == [
        (str(OK), "succeeded"),
        (str(FAILED), "failed"),
    ]
