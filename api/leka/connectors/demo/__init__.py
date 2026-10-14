"""A demonstration's sources (LEKA-449): Nova Retail's records, replayed.

A source of a demonstration workspace is built as its connector's kind —
GitHub, Jira, Datadog, Confluence, so the pipeline reads it as it reads a
customer's — but answers from `world.py`, never from its vendor: `http()`
refuses, so no request leaves LEKA, whatever asks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
)
from leka.connectors.demo.world import SOURCES, records
from leka.connectors.models import HealthStatus
from leka.connectors.schemas import RawRecord

__all__ = ["SOURCES", "Replayed", "replayed"]


class _NoCredentials(BaseModel):
    """What a replayed source is given: nothing to reach anything with."""


class Replayed(Connector[BaseModel, BaseModel]):
    """A demonstration's source: Nova Retail's records, nothing reached."""

    manifest: ClassVar[ConnectorManifest]

    def http(self, base_url: str, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        msg = "a demonstration's source reaches no system"
        raise RuntimeError(msg)

    def _held(self) -> dict[Capability, list[RawRecord]]:
        return records(self.manifest.key, datetime.now(UTC))

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            account="Nova Retail (démonstration)",
            capabilities=sorted(self._held()),
        )

    async def check_health(self) -> HealthResult:
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        return ScopeListing(options=[])

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        for record in self._held().get(capability, []):
            yield record


def replayed(cls: type[Connector[Any, Any]], config: BaseModel) -> Connector[Any, Any]:
    """A source of `cls`'s kind, in a demonstration: its own manifest and
    configuration, Nova Retail's records, no credentials, no network."""
    kind: type[Replayed] = type(f"Replayed{cls.__name__}", (Replayed,), {"manifest": cls.manifest})
    return kind(config, _NoCredentials())
