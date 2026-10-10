"""What a person types is guarded (LEKA-405): an intention asked with a
password or a card in it keeps neither — its text, its title, asked again.

Acme's company model (test_knowledge_graph); its member asks.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_decisions_api import queued  # noqa: F401 — fixture
from tests.test_sources_api import acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/intentions"


async def test_an_intention_asked_with_a_secret_keeps_none(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    asked = await client.post(
        API,
        json={"text": "Redémarre Billing API en production, mot de passe : Sup3rS3cret!"},
    )
    assert asked.status_code == 201, asked.text
    intention = asked.json()["intention"]
    assert "Sup3rS3cret" not in asked.text
    assert intention["text"].endswith("mot de passe : [redacted:password]")
    assert "Sup3rS3cret" not in intention["title"]

    again = await client.post(
        f"{API}/{intention['id']}/ask",
        json={"text": "Redémarre Billing API, rembourse la carte 4111 1111 1111 1111"},
    )
    assert again.status_code == 200, again.text
    detail = (await client.get(f"{API}/{intention['id']}")).json()
    assert detail["text"] == "Redémarre Billing API, rembourse la carte [redacted:card]"
