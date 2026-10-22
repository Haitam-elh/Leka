"""What an agent reads of one thing beside its name (2026-10-22: a database
review that sees no index, a reliability analysis that sees no replica,
judge nothing).

What these protect:
- read_entity gives a thing's attributes as the model holds them — a
  table's columns' types, keys and indexes, a database's replicas — the
  empty left out, lists and texts cut, the whole bounded, what did not fit
  named.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid

from leka.capabilities.registry import catalogue
from leka.capabilities.tools import MOST_ATTRIBUTES, MOST_ITEMS, attributes_of, handlers
from leka.db import session_factory, workspace_scope
from leka.knowledge import EntityRepository, GraphRepository, GraphService, KnowledgeService
from tests.test_context_engine import _sql, model
from tests.test_knowledge_graph import BILLING
from tests.test_sources_api import acme, fake_connector  # noqa: F401 — fixtures

_ = model  # a fixture, requested by name


def test_attributes_are_given_bounded_the_empty_left_out() -> None:
    said = attributes_of(
        {
            "indexes": [f"CREATE INDEX i{n} ON t (c{n})" for n in range(100)],
            "description": "x" * 2_000,
            "multi_az": False,
            "nothing": None,
            "none": [],
            "huge": ["y" * 400] * 60,
        }
    )
    assert len(said["indexes"]) == MOST_ITEMS  # type: ignore[arg-type]
    assert len(said["description"]) == 500  # type: ignore[arg-type]
    # False is said: it is not nothing.
    assert said["multi_az"] is False
    assert "nothing" not in said and "none" not in said
    # What did not fit is named, never silently dropped.
    assert said["cut"] == ["huge"]
    assert len(json.dumps(said)) < MOST_ATTRIBUTES + 1_000


async def test_read_entity_gives_a_thing_s_attributes(
    model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    await _sql(
        acme["acme"],
        """
        UPDATE entities SET attributes = attributes || CAST(:said AS jsonb) WHERE id = :id
        """,
        said=json.dumps({"tier": "critical", "replicas": 1}),
        id=model[BILLING],
    )
    reviewer = {d.key: d for d in catalogue()}["incident-investigation"]
    workspace = acme["acme"]
    with workspace_scope(workspace):
        async with session_factory() as session:
            bound = handlers(
                reviewer,
                GraphService(GraphRepository(session, workspace)),
                KnowledgeService(EntityRepository(session, workspace)),
            )
            read = await bound["read_entity"]({"id": str(model[BILLING])})
    said = json.loads(read.text)
    assert said["name"] == "Billing API"
    assert (said["attributes"]["tier"], said["attributes"]["replicas"]) == ("critical", 1)
