"""What an agent reads of a thing's records (2026-10-14: the architect drew
its deck from names alone — « il faut qu'il rassemble plus de
documentation »).

Acme's company model (test_knowledge_graph), its records as the ingestion
kept them.

What these protect:
- read_content answers what a thing's records say: their text as extraction
  kept it, the latest first, each cut — with their title, link, kind, and
  whether the source still shows them.
- It reads only things of the types the agent is about: anything else is
  refused (`out_of_scope`); an unknown id, `not_found`.
- Every read-only agent is offered it — the architect, which declares no
  tools, among them — and the architect takes more rounds of tools than the
  runtime's default, to read a whole documentation before it draws.
- The architect is told to read before it draws.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid

from leka.capabilities.registry import catalogue
from leka.capabilities.runs import TOOL_ROUNDS, _contents
from leka.capabilities.tools import NAMES, handlers
from leka.db import session_factory, workspace_scope
from leka.knowledge import GraphRepository, GraphService
from tests.test_context_engine import _sql, model
from tests.test_knowledge_graph import BILLING, INVOICING
from tests.test_sources_api import acme, fake_connector  # noqa: F401 — fixtures

_ = model  # a fixture, requested by name
WORDS = "Billing API facture les commandes de la boutique : une API REST, sa base billing."


def test_the_architect_reads_before_it_draws_and_takes_the_rounds_to() -> None:
    found = {d.key: d for d in catalogue()}
    architect = found["application-architecture"]
    assert "read_content" in NAMES
    # It declares no tools: every read-only one, read_content with them.
    assert architect.tools == ()
    assert architect.rounds == 30 and architect.rounds > TOOL_ROUNDS
    said = architect.instructions or ""
    assert "rassembler toute la documentation AVANT de dessiner" in said
    assert "read_content" in said
    # The others keep the runtime's default.
    assert found["code-review"].rounds is None


async def test_it_reads_what_a_thing_s_records_say_only_of_its_types(
    model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    # A record's text, as extraction kept it.
    await _sql(
        acme["acme"],
        """
        UPDATE extracted_records x
           SET result = jsonb_set(x.result, '{content}', jsonb_build_array(
                 jsonb_build_object('text', CAST(:words AS text))))
          FROM source_records s
         WHERE s.id = x.source_record_id AND s.external_id = :key
        """,
        words=WORDS,
        key=BILLING,
    )
    architect = {d.key: d for d in catalogue()}["application-architecture"]
    workspace = acme["acme"]
    with workspace_scope(workspace):
        async with session_factory() as session:
            bound = handlers(
                architect,
                GraphService(GraphRepository(session, workspace)),
                content=_contents(session, workspace),
            )
            read = await bound["read_content"]({"id": str(model[BILLING])})
            other = await bound["read_content"]({"id": str(model[INVOICING])})
            unknown = await bound["read_content"]({"id": str(uuid.uuid4())})

    assert read.outcome == "ok"
    said = json.loads(read.text)
    assert (said["name"], said["type"]) == ("Billing API", "service")
    texts = [r["text"] for r in said["records"]]
    assert WORDS in texts
    assert {"title", "url", "kind", "updated_at", "gone"} <= set(said["records"][0])
    # A business capability is not the architect's: refused, said why.
    assert (other.outcome, other.why) == ("refused", "out_of_scope")
    assert (unknown.outcome, unknown.why) == ("refused", "not_found")
