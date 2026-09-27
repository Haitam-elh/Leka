"""The contract every connector implements.

A connector is the code that knows one vendor — GitHub, Jira — and nothing
else. It is handed a configuration and credentials, both already validated
and the latter already decrypted, and answers three questions: can I get
in, what can I see, and am I healthy. Lifecycle, storage, encryption,
permissions and history are the framework's; a connector never touches the
database and never sees another source.

READ-ONLY, BY CONTRACT. LEKA never writes to a customer's system.
`read_only` is a literal True in the manifest, and a connector's HTTP
client is a read client: its one method that sends a body, `post`, goes
only to the reads a vendor offers as POST, each named by the connector.

Every HTTP call goes through `self.http()`: an httpx.AsyncClient with a
10-second timeout per call, and a transport the tests replace. The whole of
a connection test is bounded at 15 seconds by the lifecycle service.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from leka.connectors.models import HealthStatus, SourceKind

if TYPE_CHECKING:  # pragma: no cover - schemas imports this module
    from leka.connectors.schemas import RawRecord

HTTP_TIMEOUT = httpx.Timeout(10.0)
TEST_BUDGET_SECONDS = 15.0


class ConnectorCategory(enum.StrEnum):
    CODE = "code"
    PROJECT = "project"
    DOCS = "docs"
    CLOUD = "cloud"
    OBSERVABILITY = "observability"
    CHAT = "chat"


class Capability(enum.StrEnum):
    """What a source can be read for. Declared by the connector, then
    discovered for each source: a token may see repositories and not issues."""

    REPOSITORIES = "repositories"
    COMMITS = "commits"
    PULL_REQUESTS = "pull_requests"
    RELEASES = "releases"
    ISSUES = "issues"
    BRANCHES = "branches"
    # Project tools (LEKA-346). Their issues are ISSUES, as a code host's are.
    PROJECTS = "projects"
    # Cloud and infrastructure (LEKA-347). Named for what they are, and not
    # `databases`, which a documentation tool's databases would want too.
    INSTANCES = "instances"
    DB_INSTANCES = "db_instances"
    BUCKETS = "buckets"
    FUNCTIONS = "functions"
    CLUSTERS = "clusters"
    NETWORKS = "networks"
    LOAD_BALANCERS = "load_balancers"
    # Documentation tools (LEKA-346).
    SPACES = "spaces"
    PAGES = "pages"
    DATABASES = "databases"


class ConnectorManifest(BaseModel):
    """What a connector is, for the catalogue and for validation."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    key: SourceKind
    display_name: str
    category: ConnectorCategory
    auth_type: Literal["token"]
    config_schema: type[BaseModel] = Field(description="Settings that are NOT secret.")
    credentials_schema: type[BaseModel] = Field(description="Secrets, as SecretStr fields.")
    capabilities: frozenset[Capability]
    # What the connector always lists whole — no vendor filter by date, like
    # a cloud inventory. Every pass of these is a full read, so what was not
    # seen is marked gone at every pass, not once a week (leka/ingestion/sync.py).
    listed_whole: frozenset[Capability] = frozenset()
    read_only: Literal[True] = True


class ConnectionTestResult(BaseModel):
    """What a successful test found."""

    account: str | None = Field(default=None, description="Who the credentials belong to.")
    metadata: dict[str, object] = Field(default_factory=dict)
    capabilities: list[Capability] = Field(description="Declared AND actually reachable.")
    warnings: list[str] = Field(default_factory=list)


class ScopeOption(BaseModel):
    """One thing an admin can put in a source's scope — a repository, a project."""

    key: str = Field(description="What the config stores to include it: 'acme/api'.")
    name: str
    description: str | None = None
    private: bool | None = None
    updated_at: datetime | None = None


class ScopeListing(BaseModel):
    options: list[ScopeOption]
    truncated: bool = Field(
        default=False, description="More exist than were listed; the rest are not offered."
    )


class HealthResult(BaseModel):
    status: HealthStatus
    detail: str | None = None
    checked_at: datetime


class Connector[ConfigT: BaseModel, CredentialsT: BaseModel](ABC):
    """Subclass, fill in `manifest`, implement two methods, register it."""

    manifest: ClassVar[ConnectorManifest]

    def __init__(
        self,
        config: ConfigT,
        credentials: CredentialsT,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self._transport = transport

    def http(self, base_url: str, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        """The only way a connector reaches its vendor."""
        return httpx.AsyncClient(
            base_url=base_url,
            headers=headers or {},
            timeout=HTTP_TIMEOUT,
            transport=self._transport,
            follow_redirects=False,
        )

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        """Authenticate, reach what is configured, discover what is readable.

        Raises ConnectorError with a Diagnostic on any failure.
        """

    @abstractmethod
    async def check_health(self) -> HealthResult:
        """A light call, free of quota where the vendor allows it."""

    async def list_scope(self) -> ScopeListing:
        """What this source's scope can be chosen from, ignoring the current
        scope. Called before activation, so an admin picks rather than types.

        Not abstract: a connector without a scope to choose raises
        NotImplementedError, and the API says so.
        """
        raise NotImplementedError(f"{self.manifest.key} has no scope to choose")

    def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        """Stream what a source holds for one capability, page by page.

        `since` is None for an initial pass. For an incremental one it is
        when the previous successful pass started: the connector returns
        what changed after it where the vendor can filter, and everything
        where it cannot — the sync engine keeps the latest version of each
        external_id, so a record seen twice costs a write, not a duplicate.

        A failure raises ConnectorError, like the other two methods. What
        was yielded before it is valid: the engine keeps it, and the next
        pass starts from the same `since`.

        Not abstract: a connector that cannot synchronise yet still exists.
        """
        raise NotImplementedError(f"{self.manifest.key} does not synchronise yet")
