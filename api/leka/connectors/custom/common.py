"""What a custom source does the same way, whatever its API (LEKA-350).

A REST source and a GraphQL source differ in how they ask for a page and
find the next one — leka/connectors/custom/rest.py and graphql_api.py. The
rest is here, once: the secret and how it is sent, the connection test
that tries the mapping on each resource's first record, health, the scope
by resource, the records built from what the mapping reads, the bounds,
and the API's refusals as diagnostics.
"""

from __future__ import annotations

import base64
import re
from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.custom.definition import Declared, at, fields, identifier, moment
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.http import VendorHttp, refusal, retry_after, usual_code
from leka.connectors.models import HealthStatus
from leka.connectors.schemas import RawRecord

C = Capability
logger = structlog.get_logger(__name__)

MAX_PAGES = 2_000  # a resource, a pass
MAX_RECORDS = 50_000  # every resource, a pass
MAX_PAGE_BYTES = 20_000_000
# An HTTP header's name (RFC 9110's token) — and none that is the
# transport's to set.
HEADER = r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$"
TRANSPORT_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "cookie", "authorization"}
)
OPTIONAL = ("url", "state", "created_at", "updated_at", "description", "author")

Auth = Literal["none", "bearer", "header", "query", "basic"]
AUTH_HELP = (
    "How the secret is sent: none, bearer (Authorization: Bearer), header "
    "(a header of its own), query (a query parameter), basic (a user and a password)."
)
AUTH_NAME_HELP = (
    "For header or query: the header (X-API-Key) or the parameter (api_key) that carries "
    "the secret."
)


class ApiSettings(Protocol):
    """What every custom source's settings say of its authentication."""

    auth: Auth
    auth_name: str | None


def named_where_needed(auth: Auth, auth_name: str | None) -> None:
    """A header or a parameter is named, and only then; a header LEKA may
    send a secret in — not one the transport sets."""
    if auth in ("header", "query"):
        if not auth_name:
            msg = f"auth {auth!r} needs auth_name: the header or parameter to send"
            raise ValueError(msg)
        if auth == "header" and (
            not re.fullmatch(HEADER, auth_name) or auth_name.lower() in TRANSPORT_HEADERS
        ):
            msg = f"{auth_name!r} is not a header LEKA may send a secret in"
            raise ValueError(msg)
    elif auth_name:
        msg = f"auth {auth!r} takes no auth_name"
        raise ValueError(msg)


class CustomCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field.
    secret: SecretStr | None = Field(
        default=None,
        max_length=4096,
        description="The token, the API key or the password — none when auth is none.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    username: str | None = Field(
        default=None, max_length=256, description="For basic auth: the user."
    )


class DeclaredConnector[ConfigT: BaseModel, ResourceT: Declared](
    Connector[ConfigT, CustomCredentials]
):
    """A source read as its admin declared it. A subclass says how to ask
    its API: a client, a first page, every item, and what to show of a
    resource in the scope."""

    resources: Sequence[ResourceT]

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        """Each resource's first page, and the mapping tried on its first
        record: an id and a title it must find; what else it misses is a
        warning."""
        self._require_the_secret()
        counts: dict[str, int] = {}
        warnings: list[str] = []
        async with self._client() as client:
            for resource in self.resources:
                page = await self._first_page(client, resource)
                counts[resource.name] = len(page)
                if not page:
                    warnings.append(
                        f"« {resource.name} » : la première page est vide, le mapping n'a pas "
                        "pu être essayé."
                    )
                    continue
                found = fields(resource.mapping, page[0])
                _require(resource, "id", identifier(found.get("id")) is not None)
                _require(resource, "title", readable(found.get("title")))
                missing = [
                    f"{name} ({getattr(resource.mapping, name)})"
                    for name in OPTIONAL
                    if getattr(resource.mapping, name) and name not in found
                ]
                if missing:
                    warnings.append(
                        f"« {resource.name} » : rien à ces chemins dans le premier "
                        f"enregistrement — {', '.join(missing)}."
                    )
        return ConnectionTestResult(
            account=self._account(),
            metadata={"resources": counts},
            capabilities=[C.RECORDS],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        self._require_the_secret()
        async with self._client() as client:
            await self._first_page(client, self.resources[0])
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        """The resources: a record's container is its resource, so a scope
        keeps or leaves a resource whole."""
        return ScopeListing(
            options=[
                ScopeOption(key=r.name, name=r.name, description=self._describe(r))
                for r in self.resources
            ]
        )

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability is not C.RECORDS:
            msg = f"a custom source reads records, not {capability}"
            raise ValueError(msg)
        self._require_the_secret()
        fetched = datetime.now(UTC)
        total = 0
        async with self._client() as client:
            for resource in self.resources:
                unidentified = 0
                async for item in self._items(client, resource):
                    found = fields(resource.mapping, item)
                    external_id = identifier(found.get("id"))
                    if external_id is None:
                        unidentified += 1
                        continue
                    total += 1
                    if total > MAX_RECORDS:
                        raise too_many(f"plus de {MAX_RECORDS} enregistrements")
                    yield record_of(resource, external_id, found, item, fetched)
                if unidentified:
                    # Not stored — nothing tells them apart — and not a failure:
                    # the others are read. Said, so the mapping can be fixed.
                    logger.warning(
                        "custom_records_without_id",
                        resource=resource.name,
                        count=unidentified,
                        path=resource.mapping.id,
                    )

    # ── what each API does its own way ───────────────────────────────────────

    @abstractmethod
    def _client(self) -> VendorHttp:
        """The API's client, the secret sent as the admin chose."""

    @abstractmethod
    async def _first_page(self, client: VendorHttp, resource: ResourceT) -> list[dict[str, Any]]:
        """A resource's first page of records."""

    @abstractmethod
    def _items(self, client: VendorHttp, resource: ResourceT) -> AsyncIterator[dict[str, Any]]:
        """Every record of a resource, page after page."""

    @abstractmethod
    def _describe(self, resource: ResourceT) -> str:
        """What the scope shows of a resource, beside its name."""

    @abstractmethod
    def _account(self) -> str:
        """Who is connected to — the API's host."""

    # ── shared ───────────────────────────────────────────────────────────────

    def _settings(self) -> ApiSettings:
        return cast("ApiSettings", self.config)

    def _secret(self) -> str:
        secret = self.credentials.secret
        return secret.get_secret_value() if secret is not None else ""

    def _headers(self) -> dict[str, str]:
        """The headers every call carries: JSON, and the secret unless it
        goes in the query."""
        settings, secret = self._settings(), self._secret()
        headers = {"Accept": "application/json"}
        if settings.auth == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        elif settings.auth == "header" and settings.auth_name:
            headers[settings.auth_name] = secret
        elif settings.auth == "basic":
            pair = f"{self.credentials.username}:{secret}".encode()
            headers["Authorization"] = f"Basic {base64.b64encode(pair).decode()}"
        return headers

    def _query_secret(self) -> dict[str, str]:
        """The secret as a query parameter, when that is the way chosen."""
        settings = self._settings()
        if settings.auth == "query" and settings.auth_name:
            return {settings.auth_name: self._secret()}
        return {}

    def _require_the_secret(self) -> None:
        settings = self._settings()
        if settings.auth != "none" and not self._secret():
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Cette authentification demande un secret : le token, la clé ou le "
                "mot de passe.",
            )
        if settings.auth == "basic" and not self.credentials.username:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="L'authentification basic demande un utilisateur.",
            )

    def _json(self, response: httpx.Response, method: str, where: str) -> Any:
        """An answer as JSON, bounded — or a diagnostic that names where."""
        if len(response.content) > MAX_PAGE_BYTES:
            raise diagnose(
                DiagnosticCode.PROVIDER_ERROR,
                message="Une page de l'API dépasse 20 Mo : réduisez la taille des pages.",
                detail=f"{method} {where}: {len(response.content)} bytes",
            )
        try:
            return response.json()
        except ValueError:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message=f"« {where} » ne répond pas en JSON : vérifiez l'adresse.",
                detail=f"{method} {where} → {response.headers.get('content-type', '?')}",
            ) from None

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """The API's refusals, as diagnostics — in terms that fit any API."""
        secret = self._secret()
        status = response.status_code
        where = path_of(path)
        if status == 401:
            message = "L'API refuse ce secret : vérifiez-le, et la façon de l'envoyer."
            return refusal(response, where, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403:
            message = f"L'API refuse cette lecture : le secret n'a pas accès à « {where} »."
            return refusal(
                response, where, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404:
            message = f"L'API ne connaît pas « {where} » : vérifiez l'adresse et le chemin."
            return refusal(response, where, secret, DiagnosticCode.NOT_FOUND, message=message)
        if status == 429:
            return refusal(
                response,
                where,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response),
            )
        return refusal(response, where, secret, usual_code(status))


def record_of(
    resource: Declared,
    external_id: str,
    found: dict[str, Any],
    item: dict[str, Any],
    fetched: datetime,
) -> RawRecord:
    """A record as every custom source stores it — read or received:
    `{"resource", "entity", "fields", "record"}`, its id prefixed by its
    resource, its resource as its container."""
    return RawRecord(
        kind=C.RECORDS,
        external_id=external_of(resource, external_id),
        container=resource.name,
        payload={
            "resource": resource.name,
            **({"entity": resource.entity} if resource.entity else {}),
            "fields": found,
            "record": item,
        },
        updated_at=moment(found.get("updated_at")),
        fetched_at=fetched,
    )


def external_of(resource: Declared, external_id: str) -> str:
    """Ids of two resources may be the same number: the resource tells them apart."""
    return f"{resource.name}:{external_id}"


def records_at(resource: Declared, body: Any) -> list[dict[str, Any]]:
    """The records of an answer — where `items` says, or the answer itself."""
    found = at(body, resource.items) if resource.items else body
    if not isinstance(found, list):
        where = f"« {resource.items} »" if resource.items else "la réponse"
        raise diagnose(
            DiagnosticCode.CONFIG_INVALID,
            message=f"« {resource.name} » : {where} n'est pas une liste d'enregistrements. "
            "Vérifiez `items`.",
        )
    return [item for item in found if isinstance(item, dict)]


def text(value: object) -> str | None:
    """A cursor, a link: text or a number, never an object or a yes/no."""
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return str(value) or None


def path_of(url: str) -> str:
    """A page's path, without its query — which may carry the secret."""
    return httpx.URL(url).path or url


def too_many(what: str) -> ConnectorError:
    return diagnose(
        DiagnosticCode.CONFIG_INVALID,
        message=f"La lecture s'arrête : {what}. Restreignez les ressources (paramètres, "
        "périmètre) : une liste coupée ferait croire le reste supprimé.",
    )


def _require(resource: Declared, name: str, present: bool) -> None:
    if not present:
        path = getattr(resource.mapping, name)
        raise diagnose(
            DiagnosticCode.CONFIG_INVALID,
            message=f"« {resource.name} » : le premier enregistrement n'a pas de {name} "
            f"lisible à « {path} ». Vérifiez le mapping.",
        )


def readable(value: object) -> bool:
    """A value a person can read as a name: text or a number, not empty."""
    return (
        isinstance(value, str | int | float)
        and not isinstance(value, bool)
        and str(value).strip() != ""
    )
