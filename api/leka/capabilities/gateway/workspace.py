"""A workspace's say on its language model (LEKA-394): what answers here,
and its own model if it brings one — Paramètres > Modèle de langage.

    overview()  LEKA's default, its fallbacks, the providers a workspace
                may bring, its own model if any, and what would answer now
    save()      its own model: provider, model or Azure deployment, address,
                key (encrypted; never shown again — its last four
                characters are), on or off, "ours only" or not
    remove()    back to LEKA's
    choose()    which of LEKA's models answers first here — among those
                LEKA holds a key for, Gemini or Mistral — in one click
                (2026-10-21); unchoose(): LEKA's default again
    test()      asked a few words: whether it answered, how fast

A key is required to bring a model, and again when the provider changes —
a key is one vendor's. A key left out of a later change is kept.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.gateway.contract import provider, providers
from leka.capabilities.gateway.profiles import DEFAULTS, Profile, of_provider, profile
from leka.capabilities.gateway.routing import Needs, Routing, fallbacks_of
from leka.capabilities.gateway.service import (
    Gateway,
    Tested,
    default_ready,
    leka_default,
    leka_keys,
)
from leka.capabilities.models import WorkspaceModel, WorkspaceModelDefault
from leka.core.config import settings
from leka.platform import secret_box


class ModelSettingError(ValueError):
    """A model that cannot be saved as given: which field, and why."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Offered:
    """A provider a workspace may bring, and the models LEKA knows of it."""

    name: str
    title: str
    needs: frozenset[str]
    default_model: str | None
    leka_holds: bool
    models: tuple[Profile, ...]


@dataclass(frozen=True)
class Overview:
    default: Profile
    default_ready: bool
    fallbacks: tuple[Profile, ...]
    offered: tuple[Offered, ...]
    own: WorkspaceModel | None
    routing: Routing
    # Which of LEKA's models its admin chose to answer first here, and
    # those it may choose: every model of a provider LEKA holds a key for.
    chosen: Profile | None = None
    choosable: tuple[Profile, ...] = ()


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

    async def overview(self) -> Overview:
        keys = leka_keys()
        default = profile(*leka_default())
        chosen = await self._gateway.chosen()
        first, after = await self._gateway.defaults()
        fallbacks = (
            (after if chosen is not None else None)
            or fallbacks_of(settings.llm_fallbacks)
            or [
                (name, DEFAULTS[name])
                for name, key in keys.items()
                if key is not None and name != first[0] and name in DEFAULTS
            ]
        )
        offered = tuple(
            Offered(
                name=vendor.name,
                title=vendor.title,
                needs=vendor.needs,
                default_model=DEFAULTS.get(vendor.name),
                leka_holds=keys.get(vendor.name) is not None,
                models=tuple(of_provider(vendor.name)),
            )
            for vendor in providers()
        )
        return Overview(
            default=default,
            default_ready=default_ready(),
            fallbacks=tuple(profile(p, m) for p, m in fallbacks),
            offered=offered,
            own=await self._gateway.setting(),
            routing=await self._gateway.routing(Needs()),
            chosen=profile(*first) if chosen is not None and first != leka_default() else None,
            choosable=tuple(
                found
                for name, key in keys.items()
                if key is not None
                for found in of_provider(name)
            ),
        )

    async def choose(
        self, provider_name: str, model: str, *, by: uuid.UUID, now: datetime
    ) -> WorkspaceModelDefault:
        """Which of LEKA's models answers first here: one of a provider LEKA
        holds a key for, and that LEKA knows."""
        if not leka_keys().get(provider_name):
            raise ModelSettingError("provider", "LEKA holds no key for this provider here.")
        if model not in {found.model for found in of_provider(provider_name)}:
            raise ModelSettingError("model", "LEKA does not know this model.")
        row = await self._gateway.chosen()
        if row is None:
            row = WorkspaceModelDefault(workspace_id=self._workspace_id, id=uuid.uuid4())
            self._session.add(row)
        row.provider, row.model = provider_name, model
        row.changed_by, row.changed_at = by, now
        await self._session.flush()
        return row

    async def unchoose(self) -> bool:
        """LEKA's default again — False when none was chosen."""
        row = await self._gateway.chosen()
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def save(self, change: Change, *, by: uuid.UUID, now: datetime) -> WorkspaceModel:
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
