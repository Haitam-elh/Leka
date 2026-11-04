"""A workspace's own language model (LEKA-394), under an Enterprise contract
that brings it (LEKA-530) — Paramètres > Le modèle de votre entreprise.

    overview()  whether its contract brings one, the providers it may bring,
                its own model if any — never LEKA's models, their prices,
                an order of answer: the LEKA team assigns those to each
                agent (agents/models.yaml)
    save()      its own model: provider, model or Azure deployment, address,
                key (encrypted; never shown again — its last four
                characters are), on or off, "ours only" or not — refused on
                a plan that does not bring one
    remove()    back to LEKA's: always possible, on any plan
    test()      asked a few words: whether it answered, how fast

A key is required to bring a model, and again when the provider changes —
a key is one vendor's. A key left out of a later change is kept.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing import catalogue
from leka.capabilities.gateway.contract import provider, providers
from leka.capabilities.gateway.profiles import DEFAULTS
from leka.capabilities.gateway.service import Gateway, Tested
from leka.capabilities.models import WorkspaceModel
from leka.governance import plan_of
from leka.platform import secret_box


class ModelSettingError(ValueError):
    """A model that cannot be saved as given: which field, and why."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class OwnModelNotOfferedError(PermissionError):
    """Its plan does not bring a model of its own: an Enterprise contract does."""


@dataclass(frozen=True)
class Offered:
    """A provider a workspace may bring."""

    name: str
    title: str
    needs: frozenset[str]
    default_model: str | None


@dataclass(frozen=True)
class Overview:
    # Whether its contract brings a model of its own (the catalogue's own_llm).
    offered: bool
    providers: tuple[Offered, ...]
    own: WorkspaceModel | None


@dataclass(frozen=True)
class Change:
    provider: str
    model: str | None
    base_url: str | None
    api_version: str | None
    api_key: str | None
    enabled: bool
    exclusive: bool


class ModelSettings:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._gateway = Gateway(session, workspace_id)

    async def offered(self) -> bool:
        """Whether its plan brings a model of its own — an Enterprise
        contract (the catalogue's own_llm)."""
        plan = await plan_of(self._session, self._workspace_id)
        try:
            return catalogue().plan(plan.name).own_llm
        except KeyError:
            return False

    async def overview(self) -> Overview:
        return Overview(
            offered=await self.offered(),
            providers=tuple(
                Offered(
                    name=vendor.name,
                    title=vendor.title,
                    needs=vendor.needs,
                    default_model=DEFAULTS.get(vendor.name),
                )
                for vendor in providers()
            ),
            own=await self._gateway.setting(),
        )

    async def save(self, change: Change, *, by: uuid.UUID, now: datetime) -> WorkspaceModel:
        if not await self.offered():
            msg = "A model of your own comes with an Enterprise contract."
            raise OwnModelNotOfferedError(msg)
        vendor = provider(change.provider)
        if vendor is None:
            raise ModelSettingError("provider", "No such provider.")
        row = await self._gateway.setting()
        changing_vendor = row is None or row.provider != change.provider
        if "key" in vendor.needs and not change.api_key and (changing_vendor or not row):
            raise ModelSettingError("api_key", "A key is needed to use this provider.")
        if "url" in vendor.needs and not change.base_url:
            raise ModelSettingError("base_url", "This provider needs its address.")
        if "model" in vendor.needs and not change.model:
            raise ModelSettingError("model", "Say which model, or which deployment.")
        if row is None:
            row = WorkspaceModel(workspace_id=self._workspace_id, id=uuid.uuid4())
            self._session.add(row)
        row.provider = change.provider
        row.model = change.model or None
        row.base_url = change.base_url or None
        row.api_version = change.api_version or None
        if change.api_key:
            row.key_ciphertext = secret_box.encrypt(change.api_key)
            row.key_hint = change.api_key[-4:]
        row.enabled = change.enabled
        row.exclusive = change.exclusive
        # Changed: not known to answer until tested.
        row.status = "untested"
        row.status_detail = None
        row.tested_at = None
        row.changed_by = by
        row.changed_at = now
        await self._session.flush()
        return row

    async def remove(self) -> bool:
        row = await self._gateway.setting()
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def test(self) -> Tested:
        return await self._gateway.test()
