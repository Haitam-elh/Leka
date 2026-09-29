"""The generic REST connector — a system LEKA has no connector for, read as
its admin declared it (LEKA-350).

No code of its own: an address, a way to authenticate, and a definition
(leka/connectors/custom/definition.py) — which resources to read, how their
pages follow each other, what each field means. Everything else is the
framework's, as for any connector: the secret encrypted at rest and never
shown again, the connection test, the health checks, the sync, the scope
rules — by resource — the retention, the history.

READS ONLY: GET, and nothing else — a generic connector has no read that is
a POST to declare. To the configured host only: `base_url` is public and
https, checked when saved and when connecting (leka/connectors/network.py),
a resource's path is relative to it, and a next page on another host is
refused.

BOUNDED: at most 2 000 pages a resource and 50 000 records a pass. Beyond,
the pass fails and says so — a listing read whole and cut would mark the
rest gone — as a database's does past 20 000 tables.

Each record is stored with what the mapping read in it, beside the record
itself: `{"resource", "entity", "fields", "record"}` — `entity` when the
resource declares one. Extraction reads the fields
(leka/ingestion/extraction/custom.py); a mapping changed changes them, and
so what is extracted.

Every pass reads everything: an API's own "changed since" is too various to
trust from a declaration, and the sync writes only what changed.
"""

from __future__ import annotations

import base64
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal, Self

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.custom.definition import (
    DEFINITION_MAX,
    Definition,
    Resource,
    at,
    fields,
    identifier,
    moment,
    parse,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.http import (
    Params,
    VendorHttp,
    on_the_host,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.network import PublicHttpsUrl
from leka.connectors.registry import register_connector
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


class CustomRestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: PublicHttpsUrl = Field(
        description="The API's address, https and public: https://api.acme.com/v2. "
        "Each resource's path is read from it."
    )
    auth: Auth = Field(
        default="bearer",
        description="How the secret is sent: none, bearer (Authorization: Bearer), header "
        "(a header of its own), query (a query parameter), basic (a user and a password).",
    )
    auth_name: str | None = Field(
        default=None,
        max_length=64,
        description="For header or query: the header (X-API-Key) or the parameter (api_key) "
        "that carries the secret.",
    )
    definition: str = Field(
        min_length=2,
        max_length=DEFINITION_MAX,
        description="What to read and what it means — resources, pagination, mapping — as JSON.",
        json_schema_extra={"format": "json"},
    )

    @field_validator("definition")
    @classmethod
    def _readable(cls, value: str) -> str:
        parse(value)
        return value

    @model_validator(mode="after")
    def _named_where_needed(self) -> Self:
        if self.auth in ("header", "query"):
            if not self.auth_name:
                msg = f"auth {self.auth!r} needs auth_name: the header or parameter to send"
                raise ValueError(msg)
            if self.auth == "header" and (
                not re.fullmatch(HEADER, self.auth_name)
                or self.auth_name.lower() in TRANSPORT_HEADERS
            ):
                msg = f"{self.auth_name!r} is not a header LEKA may send a secret in"
                raise ValueError(msg)
        elif self.auth_name:
            msg = f"auth {self.auth!r} takes no auth_name"
            raise ValueError(msg)
        return self


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


@register_connector
class CustomRestConnector(Connector[CustomRestConfig, CustomCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.CUSTOM_REST,
        display_name="API REST",
        category=ConnectorCategory.CUSTOM,
        auth_type="token",
        config_schema=CustomRestConfig,
        credentials_schema=CustomCredentials,
        capabilities=frozenset({C.RECORDS}),
        # Read whole each pass (the module's docstring).
        listed_whole=frozenset({C.RECORDS}),
    )

    def __init__(
        self,
        config: CustomRestConfig,
        credentials: CustomCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config, credentials, transport=transport)
        self.definition: Definition = parse(config.definition)

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        """Each resource's first page, and the mapping tried on its first
        record: an id and a title it must find; what else it misses is a
        warning."""
        self._require_the_secret()
        counts: dict[str, int] = {}
        warnings: list[str] = []
        async with self._client() as client:
            for resource in self.definition.resources:
                page = await self._first_page(client, resource)
                counts[resource.name] = len(page)
                if not page:
                    warnings.append(
                        f"« {resource.name} » : la première page est vide, le mapping n'a pas "
                        "pu être essayé."
                    )
                    continue
                found = fields(resource.mapping, page[0])
                self._require(resource, found, "id", identifier(found.get("id")) is not None)
                self._require(resource, found, "title", _scalar(found.get("title")))
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
            account=self.config.base_url.host,
            metadata={"resources": counts},
            capabilities=[C.RECORDS],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        self._require_the_secret()
        async with self._client() as client:
            await self._first_page(client, self.definition.resources[0])
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        """The resources: a record's container is its resource, so a scope
        keeps or leaves a resource whole."""
        return ScopeListing(
            options=[
                ScopeOption(key=resource.name, name=resource.name, description=resource.path)
                for resource in self.definition.resources
            ]
        )

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability is not C.RECORDS:
            msg = f"a REST source reads records, not {capability}"
            raise ValueError(msg)
        self._require_the_secret()
        fetched = datetime.now(UTC)
        total = 0
        async with self._client() as client:
            for resource in self.definition.resources:
                unidentified = 0
                async for item in self._items(client, resource):
                    found = fields(resource.mapping, item)
                    external_id = identifier(found.get("id"))
                    if external_id is None:
                        unidentified += 1
                        continue
                    total += 1
                    if total > MAX_RECORDS:
                        raise _too_many(f"plus de {MAX_RECORDS} enregistrements")
                    yield RawRecord(
                        kind=C.RECORDS,
                        external_id=f"{resource.name}:{external_id}",
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
                if unidentified:
                    # Not stored — nothing tells them apart — and not a failure:
                    # the others are read. Said, so the mapping can be fixed.
                    logger.warning(
                        "custom_records_without_id",
                        resource=resource.name,
                        count=unidentified,
                        path=resource.mapping.id,
                    )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        """The API's client, the secret sent as the admin chose."""
        secret = self._secret()
        headers = {"Accept": "application/json"}
        if self.config.auth == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        elif self.config.auth == "header" and self.config.auth_name:
            headers[self.config.auth_name] = secret
        elif self.config.auth == "basic":
            pair = f"{self.credentials.username}:{secret}".encode()
            headers["Authorization"] = f"Basic {base64.b64encode(pair).decode()}"
        client = self.http(str(self.config.base_url), headers)
        return VendorHttp(client, secret=secret, refuse=self._refuse, page_size=0)

    def _secret(self) -> str:
        secret = self.credentials.secret
        return secret.get_secret_value() if secret is not None else ""

    def _require_the_secret(self) -> None:
        if self.config.auth != "none" and not self._secret():
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Cette authentification demande un secret : le token, la clé ou le "
                "mot de passe.",
            )
        if self.config.auth == "basic" and not self.credentials.username:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="L'authentification basic demande un utilisateur.",
            )

    def _require(self, resource: Resource, found: dict[str, Any], name: str, present: bool) -> None:
        if not present:
            path = getattr(resource.mapping, name)
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message=f"« {resource.name} » : le premier enregistrement n'a pas de {name} "
                f"lisible à « {path} ». Vérifiez le mapping.",
            )

    async def _get(
        self, client: VendorHttp, url: str, params: Params
    ) -> tuple[httpx.Response, Any]:
        """One page, as JSON — with the secret as a parameter when that is
        the way chosen."""
        if self.config.auth == "query" and self.config.auth_name:
            params = {**params, self.config.auth_name: self._secret()}
        response = await client.get(url, params=params)
        if len(response.content) > MAX_PAGE_BYTES:
            raise diagnose(
                DiagnosticCode.PROVIDER_ERROR,
                message="Une page de l'API dépasse 20 Mo : réduisez la taille des pages.",
                detail=f"GET {_path(url)}: {len(response.content)} bytes",
            )
        try:
            return response, response.json()
        except ValueError:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message=f"« {_path(url)} » ne répond pas en JSON : vérifiez le chemin.",
                detail=f"GET {_path(url)} → {response.headers.get('content-type', '?')}",
            ) from None

    async def _first_page(self, client: VendorHttp, resource: Resource) -> list[dict[str, Any]]:
        _response, body = await self._get(client, resource.path, self._params(resource))
        return _records(resource, body)

    def _params(self, resource: Resource, **more: str | int) -> Params:
        pagination = resource.pagination
        params: dict[str, str | int | list[str]] = dict(resource.params)
        if pagination.size_param:
            params[pagination.size_param] = pagination.size
        if pagination.type in ("page", "offset") and pagination.param:
            params[pagination.param] = pagination.first
        return {**params, **more}

    async def _items(self, client: VendorHttp, resource: Resource) -> AsyncIterator[dict[str, Any]]:
        """Every record of a resource, page after page, as its pagination says."""
        pagination = resource.pagination
        url: str | None = resource.path
        params = self._params(resource)
        position = pagination.first
        cursor: object = None
        pages = 0
        asked: set[str] = set()
        while url is not None:
            asked.add(self._where(url, params))
            response, body = await self._get(client, url, params)
            page = _records(resource, body)
            for item in page:
                yield item
            pages += 1
            url, following = None, None
            if pagination.type == "link":
                following = response.links.get("next", {}).get("url")
            elif pagination.type == "next_url" and pagination.next:
                following = _text(at(body, pagination.next))
            elif pagination.type == "cursor" and pagination.next and pagination.param:
                token = at(body, pagination.next)
                # An empty token ends the listing; the same one again would
                # loop on the same page.
                if _text(token) and token != cursor:
                    cursor = token
                    url, params = (
                        resource.path,
                        self._params(resource, **{pagination.param: str(token)}),
                    )
            elif pagination.type in ("page", "offset") and pagination.param:
                full = len(page) >= pagination.size if pagination.size_param else bool(page)
                if page and full:
                    position += 1 if pagination.type == "page" else len(page)
                    url, params = (
                        resource.path,
                        self._params(resource, **{pagination.param: position}),
                    )
            if following:
                base = httpx.URL(str(self.config.base_url))
                url, params = _split(on_the_host(base, following, self._secret()))
                if self._where(url, params) in asked:
                    # A link back to a page already read ends the listing,
                    # as a cursor given again does.
                    url = None
            if url is not None:
                if pages >= MAX_PAGES:
                    raise _too_many(f"plus de {MAX_PAGES} pages pour « {resource.name} »")
                client.spare_the_quota(response)

    def _where(self, url: str, params: Params) -> str:
        """A page's full address and query, the same whether it was a path
        from the base — as httpx joins them — or a link, however its query
        was given."""
        full = url if "://" in url else str(self.config.base_url).rstrip("/") + url
        return str(httpx.URL(full).copy_merge_params(dict(params)))

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """The API's refusals, as diagnostics — in terms that fit any API."""
        secret = self._secret()
        status = response.status_code
        where = _path(path)
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


def _split(url: str) -> tuple[str, Params]:
    """A next page's URL as its address and its query — the query handed
    back as parameters, so that it is kept, and a secret sent as one joins
    it. A parameter given twice stays a list."""
    link = httpx.URL(url)
    params: dict[str, str | int | list[str]] = {}
    for key in link.params:
        values = link.params.get_list(key)
        params[key] = values if len(values) > 1 else values[0]
    return str(link.copy_with(query=None)), params


def _records(resource: Resource, body: Any) -> list[dict[str, Any]]:
    """The records of a page — where `items` says, or the page itself."""
    found = at(body, resource.items) if resource.items else body
    if not isinstance(found, list):
        where = f"« {resource.items} »" if resource.items else "la réponse"
        raise diagnose(
            DiagnosticCode.CONFIG_INVALID,
            message=f"« {resource.name} » : {where} n'est pas une liste d'enregistrements. "
            "Vérifiez `items`.",
        )
    return [item for item in found if isinstance(item, dict)]


def _text(value: object) -> str | None:
    return (
        str(value)
        if isinstance(value, str | int) and not isinstance(value, bool) and str(value)
        else None
    )


def _scalar(value: object) -> bool:
    return (
        isinstance(value, str | int | float)
        and not isinstance(value, bool)
        and str(value).strip() != ""
    )


def _path(url: str) -> str:
    """A page's path, without its query — which may carry the secret."""
    return httpx.URL(url).path or url


def _too_many(what: str) -> ConnectorError:
    return diagnose(
        DiagnosticCode.CONFIG_INVALID,
        message=f"La lecture s'arrête : {what}. Restreignez les ressources (paramètres, "
        "périmètre) : une liste coupée ferait croire le reste supprimé.",
    )
