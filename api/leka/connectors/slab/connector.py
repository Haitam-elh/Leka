"""The Slab connector — slab.com, through its GraphQL API.

Slab has one endpoint, POST https://api.slab.com/v1/graphql, and speaks
only GraphQL, like Linear and Monday. Every document this connector sends
is below, as a constant, and is a `query`: `read_only` refuses a
`mutation` or a `subscription` before it is sent, and a test runs it over
every document.

Slab's API belongs to its Business and Enterprise plans. Its token is the
workspace's, from Team settings → Developer, and reads as the Slab Bot: it
sees what the bot was given, and no more. That is the boundary.

test_connection: which organisation (`organization`), what can I see —
its topics, its posts — and can I read a post's content.

check_health: `organization { id }`. Slab sends no quota headers.

list_scope: every topic the bot sees.

iter_resources: topics, whole each pass; posts — each asked on its own,
since Slab gives a post's content only one post at a time. The list of
posts comes whole; an incremental pass asks the content of those updated
since the last one. With `topics`, a post is read when one of its topics
is in scope.

Slab does not publish its limit; the client keeps to four requests a
second rather than be refused halfway through a pass.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from leka.connectors import graphql
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
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.graphql import errors_of
from leka.connectors.http import (
    Item,
    Pace,
    VendorHttp,
    dig,
    parse_timestamp,
    record,
    refusal,
    retry_after,
    usual_code,
)
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

API = "https://api.slab.com"
GRAPHQL = "/v1/graphql"
MAX_SCOPE_OPTIONS = 1000
# Seconds between two requests: Slab publishes no limit, and throttles.
MIN_INTERVAL = 0.25
# A post's updatedAt is written a moment after the change.
UPDATE_MARGIN = timedelta(minutes=2)
TOPIC_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Slab's words for a request it will not answer yet.
BUSY = re.compile(r"rate|throttl|too many|complexity", re.IGNORECASE)
UNAUTHENTICATED = re.compile(r"unauthori[sz]ed|unauthenticated|invalid token", re.IGNORECASE)
FORBIDDEN = re.compile(r"forbidden|permission|not allowed", re.IGNORECASE)
NOT_FOUND = re.compile(r"not found|does not exist", re.IGNORECASE)

# ── the documents: queries, nothing else ─────────────────────────────────────

ORGANIZATION = """
query Organization { organization { id name } }
"""

HEALTH = """
query Health { organization { id } }
"""

TOPICS = """
query Topics { organization { topics { id name description } } }
"""

POSTS = """
query Posts { organization { posts { id title insertedAt updatedAt publishedAt } } }
"""

TOPIC_POSTS = """
query TopicPosts($id: ID!) { topic(id: $id) { id posts { id } } }
"""

POST = """
query Post($id: ID!) {
  post(id: $id) { id title content insertedAt updatedAt publishedAt linkAccess }
}
"""

DOCUMENTS = (ORGANIZATION, HEALTH, TOPICS, POSTS, TOPIC_POSTS, POST)


def read_only(document: str) -> str:
    """The document, if it only reads (leka/connectors/graphql.py)."""
    return graphql.read_only(document, "Slab")


class SlabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="Ids of the topics whose posts to read. Empty: every post the Slab Bot "
        "can see.",
    )

    @field_validator("topics")
    @classmethod
    def _ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        ids = [topic.strip() for topic in value]
        for topic in ids:
            if not TOPIC_ID.match(topic):
                msg = f"{topic!r} is not the id of a Slab topic"
                raise ValueError(msg)
        return list(dict.fromkeys(ids))


class SlabCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(
        min_length=20,
        description="The API token, from Team settings → Developer.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class SlabConnector(Connector[SlabConfig, SlabCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.SLAB,
        display_name="Slab",
        category=ConnectorCategory.DOCS,
        auth_type="token",
        config_schema=SlabConfig,
        credentials_schema=SlabCredentials,
        capabilities=frozenset({Capability.SPACES, Capability.PAGES}),
        # Topics come whole every pass; posts are kept by their last update.
        listed_whole=frozenset({Capability.SPACES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._client() as client:
            organization = dig(await self._query(client, ORGANIZATION), "organization") or {}
            topics = await self._topics(client)
            self._require_scope(topics)
            posts = await self._posts(client)
            capabilities = [Capability.SPACES] if topics else []
            warnings: list[str] = []
            if posts:
                try:
                    await self._query(client, POST, {"id": str(posts[0]["id"])})
                    capabilities.append(Capability.PAGES)
                except ConnectorError:
                    pass  # a capability left out, not a failed test
            if not topics and not posts:
                warnings.append(
                    "Le Slab Bot ne voit aucun sujet ni article. Dans Slab, donnez-lui accès aux "
                    "sujets que LEKA doit lire."
                )

        return ConnectionTestResult(
            account=str(organization.get("name") or "Slab"),
            metadata={"topics_visible": len(topics), "posts_visible": len(posts)},
            capabilities=capabilities,
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._client() as client:
            await self._query(client, HEALTH)
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with self._client() as client:
            topics = await self._topics(client)
        options = [
            ScopeOption(
                key=str(topic["id"]),
                name=str(topic.get("name") or topic["id"]),
                description=_text(topic.get("description")),
            )
            for topic in topics[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(topics) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"Slab does not read {capability}"
            raise ValueError(msg)
        async with self._client() as client:
            if capability is Capability.SPACES:
                wanted = set(self.config.topics or [])
                for topic in await self._topics(client):
                    if wanted and str(topic["id"]) not in wanted:
                        continue
                    yield record(capability, topic, external_id=str(topic["id"]))
                return
            where = await self._scope_of_posts(client)
            after = since - UPDATE_MARGIN if since else None
            for listed in await self._posts(client):
                post_id = str(listed["id"])
                if where is not None and post_id not in where:
                    continue
                updated = parse_timestamp(listed.get("updatedAt"))
                if after and updated is not None and updated < after:
                    continue
                post = dig(await self._query(client, POST, {"id": post_id}), "post")
                if not isinstance(post, dict):
                    continue  # gone since the listing: swept
                yield record(
                    capability,
                    post,
                    external_id=post_id,
                    container=where.get(post_id) if where is not None else None,
                    updated=post.get("updatedAt"),
                )

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> VendorHttp:
        secret = self.credentials.token.get_secret_value()
        client = self.http(
            API,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "LEKA",
                # Slab's token goes as it is.
                "Authorization": secret,
            },
        )
        client.event_hooks = {"request": [Pace(MIN_INTERVAL)], "response": []}
        return VendorHttp(
            client,
            secret=secret,
            refuse=self._refuse,
            page_size=0,  # Slab does not page these answers
            reads_by_post=frozenset({GRAPHQL}),
        )

    async def _query(
        self, client: VendorHttp, document: str, variables: Mapping[str, object] | None = None
    ) -> Any:
        """The `data` of one query, or the diagnostic of what Slab refused."""
        body: dict[str, object] = {"query": read_only(document)}
        if variables:
            body["variables"] = dict(variables)
        response = await client.post(GRAPHQL, body)
        if errors_of(response):
            raise self._refuse(response, GRAPHQL, "")
        return response.json().get("data") or {}

    async def _topics(self, client: VendorHttp) -> list[Item]:
        found = dig(await self._query(client, TOPICS), "organization.topics")
        return found if isinstance(found, list) else []

    async def _posts(self, client: VendorHttp) -> list[Item]:
        found = dig(await self._query(client, POSTS), "organization.posts")
        return found if isinstance(found, list) else []

    async def _scope_of_posts(self, client: VendorHttp) -> dict[str, str] | None:
        """The posts of the topics in scope, each with the first topic in
        scope that holds it — or None when every post is wanted."""
        if not self.config.topics:
            return None
        where: dict[str, str] = {}
        for topic in self.config.topics:
            posts = dig(await self._query(client, TOPIC_POSTS, {"id": topic}), "topic.posts")
            for post in posts if isinstance(posts, list) else []:
                where.setdefault(str(post["id"]), topic)
        return where

    def _require_scope(self, topics: list[Item]) -> None:
        """Every topic in scope must be one the Slab Bot can see."""
        known = {str(topic["id"]) for topic in topics}
        missing = [topic for topic in self.config.topics or [] if topic not in known]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Slab ne montre pas ces sujets au Slab Bot : {named}.",
            )

    def _refuse(self, response: httpx.Response, path: str, missing: str) -> ConnectorError:
        """Slab's refusals, as diagnostics: the HTTP status, else what its
        errors say — Slab gives them no code."""
        secret = self.credentials.token.get_secret_value()
        status = response.status_code
        said = " ".join(str(error.get("message", "")) for error in errors_of(response))
        if status == 429 or BUSY.search(said):
            return refusal(
                response,
                path,
                secret,
                DiagnosticCode.RATE_LIMITED,
                retry_after=retry_after(response) or 60,
            )
        if status == 401 or UNAUTHENTICATED.search(said):
            message = "Slab refuse ce token d'API."
            return refusal(response, path, secret, DiagnosticCode.AUTH_INVALID, message=message)
        if status == 403 or FORBIDDEN.search(said):
            message = "Slab refuse cette lecture : l'API demande une offre Business ou Enterprise."
            return refusal(
                response, path, secret, DiagnosticCode.PERMISSION_DENIED, message=message
            )
        if status == 404 or NOT_FOUND.search(said):
            message = "Slab ne trouve pas ce sujet, ou le Slab Bot ne le voit pas."
            return refusal(response, path, secret, DiagnosticCode.NOT_FOUND, message=message)
        if status >= 500:
            return refusal(response, path, secret, DiagnosticCode.PROVIDER_ERROR)
        return refusal(response, path, secret, usual_code(status))


def _text(value: object) -> str | None:
    """A topic's description, as text: Slab may give it as a string or as
    rich text (a Quill delta, in JSON)."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [str(op.get("insert", "")) for op in value if isinstance(op, dict)]
        return "".join(parts).strip() or None
    return None
