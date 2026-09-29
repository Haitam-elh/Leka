"""The generic GraphQL connector — a system LEKA has no connector for, read
through its GraphQL API as its admin declared it (LEKA-350).

As the REST one (leka/connectors/custom/rest.py), and sharing all it can
(common.py): an endpoint, a way to send the secret, a definition — for each
resource, a query document, its variables, where its records are in the
answer, how its pages follow, what its fields mean.

READS ONLY — THROUGH POST. GraphQL answers everything through POST, so
"LEKA reads" rests on the documents: each is a `query`, checked when the
definition is saved (leka/connectors/graphql.py refuses a `mutation` or a
`subscription`, even in a comment), and POSTed to the endpoint's path and
no other (`reads_by_post`).

A GraphQL API refuses in two ways: an HTTP error, read as the REST one's,
or a 200 whose body carries `errors`. The second fails the call too, even
beside partial `data`: a page read in part would mark the rest gone.

Pages follow by cursor: the end cursor sent back as a variable while the
API says there is more (`hasNextPage`), or while the cursor is new.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from leka.connectors.base import Capability, ConnectorCategory, ConnectorManifest
from leka.connectors.custom import common
from leka.connectors.custom.common import (
    AUTH_HELP,
    AUTH_NAME_HELP,
    Auth,
    CustomCredentials,
    DeclaredConnector,
    named_where_needed,
    records_at,
    text,
    too_many,
)
from leka.connectors.custom.definition import (
    DEFINITION_MAX,
    GraphQLResource,
    at,
    parse_graphql,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.graphql import errors_of
from leka.connectors.http import VendorHttp
from leka.connectors.models import SourceKind
from leka.connectors.network import PublicHttpsUrl
from leka.connectors.registry import register_connector

C = Capability
# What a GraphQL server writes in `extensions.code` — Apollo's words, and the
# ones others borrowed.
UNAUTHENTICATED = frozenset({"UNAUTHENTICATED", "UNAUTHORIZED", "AUTHENTICATION_ERROR"})
FORBIDDEN = frozenset({"FORBIDDEN", "ACCESS_DENIED"})
MISWRITTEN = frozenset(
    {"GRAPHQL_VALIDATION_FAILED", "GRAPHQL_PARSE_FAILED", "BAD_USER_INPUT", "BAD_REQUEST"}
)
THROTTLED = frozenset({"RATE_LIMITED", "THROTTLED", "TOO_MANY_REQUESTS"})


class CustomGraphQLConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: PublicHttpsUrl = Field(
        description="The GraphQL endpoint, https and public: https://api.acme.com/graphql."
    )
    auth: Auth = Field(default="bearer", description=AUTH_HELP)
    auth_name: str | None = Field(default=None, max_length=64, description=AUTH_NAME_HELP)
    definition: str = Field(
        min_length=2,
        max_length=DEFINITION_MAX,
        description="What to read and what it means — queries, pagination, mapping — as JSON.",
        json_schema_extra={"format": "json"},
    )

    @field_validator("endpoint")
    @classmethod
    def _no_query(cls, value: Any) -> Any:
        if value.query:
            msg = "the endpoint takes no query: the query is in the definition's documents"
            raise ValueError(msg)
        return value

    @field_validator("definition")
    @classmethod
    def _readable(cls, value: str) -> str:
        parse_graphql(value)
        return value

    @model_validator(mode="after")
    def _named_where_needed(self) -> Self:
        named_where_needed(self.auth, self.auth_name)
        return self


@register_connector
class CustomGraphQLConnector(DeclaredConnector[CustomGraphQLConfig, GraphQLResource]):
    manifest = ConnectorManifest(
        key=SourceKind.CUSTOM_GRAPHQL,
        display_name="API GraphQL",
        category=ConnectorCategory.CUSTOM,
        auth_type="token",
        config_schema=CustomGraphQLConfig,
        credentials_schema=CustomCredentials,
        capabilities=frozenset({C.RECORDS}),
        # Read whole each pass, as the REST connector.
        listed_whole=frozenset({C.RECORDS}),
    )

    def __init__(
        self,
        config: CustomGraphQLConfig,
        credentials: CustomCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config, credentials, transport=transport)
        self.resources = parse_graphql(config.definition).resources
        url = httpx.URL(str(config.endpoint))
        self._origin = str(url.copy_with(path="/", query=None, fragment=None)).rstrip("/")
        self._path = url.path or "/"

    def _client(self) -> VendorHttp:
        client = self.http(self._origin, {**self._headers(), "Content-Type": "application/json"})
        return VendorHttp(
            client,
            secret=self._secret(),
            refuse=self._refuse,
            page_size=0,
            reads_by_post=frozenset({self._path}),
        )

    def _describe(self, resource: GraphQLResource) -> str:
        return str(resource.items)

    def _account(self) -> str:
        return str(self.config.endpoint.host)

    async def _ask(
        self, client: VendorHttp, resource: GraphQLResource, cursor: str | None = None
    ) -> tuple[httpx.Response, Any]:
        """One answer to a resource's query — its variables, the page size,
        the cursor — or a diagnostic, whether the API refused by status or
        by `errors`."""
        pagination = resource.pagination
        variables: dict[str, Any] = dict(resource.variables)
        if pagination.size_variable:
            variables[pagination.size_variable] = pagination.size
        if cursor is not None and pagination.variable:
            variables[pagination.variable] = cursor
        response = await client.post(
            self._path,
            {"query": resource.query, "variables": variables},
            params=self._query_secret() or None,
        )
        body = self._json(response, "POST", self._path)
        errors = errors_of(response)
        if errors:
            raise self._refused(resource, errors)
        return response, body

    async def _first_page(
        self, client: VendorHttp, resource: GraphQLResource
    ) -> list[dict[str, Any]]:
        _response, body = await self._ask(client, resource)
        return records_at(resource, body)

    async def _items(
        self, client: VendorHttp, resource: GraphQLResource
    ) -> AsyncIterator[dict[str, Any]]:
        """Every record of a resource, cursor after cursor."""
        pagination = resource.pagination
        cursor: str | None = None
        seen: set[str] = set()
        pages = 0
        while True:
            response, body = await self._ask(client, resource, cursor)
            for item in records_at(resource, body):
                yield item
            pages += 1
            if pagination.type != "cursor" or not pagination.next:
                return
            following = text(at(body, pagination.next))
            more = at(body, pagination.has_next) if pagination.has_next else following is not None
            # The API says it is done, or gives a cursor already read: done.
            if more is not True or following is None or following in seen:
                return
            seen.add(following)
            cursor = following
            if pages >= common.MAX_PAGES:
                raise too_many(f"plus de {common.MAX_PAGES} pages pour « {resource.name} »")
            client.spare_the_quota(response)

    def _refused(self, resource: GraphQLResource, errors: list[Any]) -> ConnectorError:
        """A 200 that carries `errors`, as a diagnostic: by the code the
        server put in `extensions`, the server's own words in the detail,
        cleaned of the secret."""
        codes = {
            str(code).upper()
            for error in errors
            if isinstance(error, dict)
            and (code := (error.get("extensions") or {}).get("code")) is not None
        }
        said = "; ".join(
            str(error.get("message"))[:200] for error in errors[:3] if isinstance(error, dict)
        )
        detail = f"POST {self._path}: {said}" if said else f"POST {self._path}"
        secrets = [self._secret()]
        if codes & UNAUTHENTICATED:
            return diagnose(
                DiagnosticCode.AUTH_INVALID,
                message="L'API refuse ce secret : vérifiez-le, et la façon de l'envoyer.",
                detail=detail,
                secrets=secrets,
            )
        if codes & FORBIDDEN:
            return diagnose(
                DiagnosticCode.PERMISSION_DENIED,
                message=f"L'API refuse la lecture de « {resource.name} » à ce secret.",
                detail=detail,
                secrets=secrets,
            )
        if codes & MISWRITTEN:
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message=f"L'API refuse la requête de « {resource.name} » : vérifiez-la, et ses "
                "variables, dans la définition.",
                detail=detail,
                secrets=secrets,
            )
        if codes & THROTTLED:
            return diagnose(DiagnosticCode.RATE_LIMITED, detail=detail, secrets=secrets)
        return diagnose(
            DiagnosticCode.PROVIDER_ERROR,
            message=f"L'API répond à « {resource.name} » par des erreurs.",
            detail=detail,
            secrets=secrets,
        )
