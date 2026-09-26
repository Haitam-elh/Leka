# Adding a connector

GitHub is the example: `api/leka/connectors/github/`. A new connector touches
**its own package and two lines elsewhere**, nothing in the platform.

## 1. The kind

Add the member to `SourceKind` in `api/leka/connectors/models.py`, if it is
not there:

```python
class SourceKind(enum.StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"   # new
```

No migration: the database does not check this list (it did until LEKA-344).

## 2. The package

```
api/leka/connectors/gitlab/
    __init__.py      # re-exports the connector, so importing it registers it
    connector.py
```

### Config and credentials

Two Pydantic models. **Settings in one, secrets in the other**, every secret
a `SecretStr` marked write-only — the catalogue turns both into the JSON
Schemas the frontend builds its form from.

```python
class GitHubConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization: str | None = None
    base_url: HttpUrl = HttpUrl("https://api.github.com")

class GitHubCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=20, json_schema_extra={"format": "password", "writeOnly": True})
```

`extra="forbid"`: a typo in a field name is refused, not silently ignored.

### The class

```python
@register_connector
class GitHubConnector(Connector[GitHubConfig, GitHubCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GITHUB,
        display_name="GitHub",
        category=ConnectorCategory.CODE,
        auth_type="token",
        config_schema=GitHubConfig,
        credentials_schema=GitHubCredentials,
        capabilities=frozenset({Capability.REPOSITORIES, Capability.COMMITS, ...}),
    )

    async def test_connection(self) -> ConnectionTestResult: ...
    async def check_health(self) -> HealthResult: ...
```

### test_connection

Three things, in order, and stop at the first failure:

1. **Authenticate** — the cheapest call that needs the credentials (`GET /user`).
2. **Reach what is configured** — the organisation, the project (`GET /orgs/{org}`).
3. **Discover** — which declared capabilities this source can really read.
   GitHub lists one page of repositories, then probes one repository for
   commits, pull requests, releases and issues, **in parallel**
   (`asyncio.gather`): the whole test must fit in 15 seconds.

Return what an admin wants to see (`account`, `metadata`), the capabilities
found, and `warnings` for what works but should not be so — a token that
can write, when LEKA only reads.

### list_scope and iter_resources (optional)

`list_scope()` returns what an admin can put in the source's scope — its
projects, its repositories — ignoring the current scope.
`iter_resources(capability, since=...)` streams `RawRecord`s for the sync
engine; read `since` where the vendor can filter by date. GitHub's are the
example. A connector without them raises `NotImplementedError` and still works.

### check_health

One light call, free of quota when the vendor has one (`GET /rate_limit`).
`degraded` when the source works but is close to a limit.

### Errors

Every failure becomes a `ConnectorError` through `diagnose(...)`, **with the
secret passed in** so it is removed from the detail:

```python
raise diagnose(DiagnosticCode.AUTH_INVALID, provider_status=401, detail=body, secrets=[token])
```

Map the vendor's answers to the codes of
[framework.md](framework.md#diagnostics); GitHub's mapping is `_diagnose` in
`connector.py`. Timeouts and transport errors: `TIMEOUT` and
`NETWORK_UNREACHABLE`.

### HTTP

Only through `self.http(base_url, headers=...)`, wrapped in
`leka.connectors.http.VendorHttp` — it sets the 10-second timeout, and it is
how the tests replace the network. `VendorHttp` gives `get` (a failure
becomes a diagnostic through your `refuse`), `pages` (the Link header, or
the body with `in_body=("values", "next")` — a field may be a path,
`("results", "_links.next")` — relative links read against the base URL,
never to another host nor down to `http`; `updated_field` for
`stop_before` may be a path too, `"version.createdAt"`), `probe`,
and `get_if_answered` for what a vendor may not answer. `refusal`,
`usual_code`, `retry_after`, `record` and `records` do the rest; a
connector writes only what its vendor means — which 403 is a quota, which a
scope.

## 3. Register it

One line in `api/leka/connectors/__init__.py`:

```python
from leka.connectors import (
    github,  # noqa: F401  — registers GitHubConnector
    gitlab,  # noqa: F401  — registers GitLabConnector
)
```

That is the whole registry. It appears in `GET /connectors/catalog`.

## 4. Test it without the network

`httpx.MockTransport` answers in place of the vendor — see
`api/tests/test_github_connector.py`. At minimum: success, invalid
credentials, permission denied, the configured resource missing, rate
limiting, a timeout, a 5xx, and the secret absent from every diagnostic.

```python
connector = GitHubConnector(config, credentials, transport=httpx.MockTransport(handler))
```

Through the API, override `get_connector_transport` in
`app.dependency_overrides` (`api/tests/test_sources_api.py`).

## Checklist

- [ ] `SourceKind` member
- [ ] config and credentials models, `extra="forbid"`, secrets as write-only `SecretStr`
- [ ] `test_connection` in three steps, parallel probes, under 15 s
- [ ] `check_health`, quota-free if possible
- [ ] every failure through `diagnose(..., secrets=[...])`
- [ ] every call a GET, through `self.http()` and `VendorHttp`
- [ ] one import line in `connectors/__init__.py`
- [ ] tests with `MockTransport`, no network
