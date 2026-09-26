# Project and documentation tools — what LEKA asks for, and what it reads

Jira and Confluence, through [the connector framework](framework.md).
LEKA-346.
**LEKA only reads**: every call is a GET, to the customer's Atlassian Cloud
site and nowhere else.

---

## Atlassian Cloud

Jira and Confluence are read at `https://<site>.atlassian.net`, as an
Atlassian account, with one of its API tokens. One account and one token
can serve both sources.

**The site is a name, never an address.** The form takes `acme`, or a
pasted `https://acme.atlassian.net/jira/…`, and keeps `acme`; LEKA builds
the host itself, always under `atlassian.net`. Anything else — another
domain, an IP address, a port — is refused when the source is saved. A
connector whose host could be typed would let whoever may add a source aim
LEKA's requests inside its own network.

**An API token can do everything its account can.** Atlassian cannot
narrow a classic token to reading, so the account is what limits LEKA:

1. Create a dedicated account — `leka@acme.com`, say — with access to
   Jira and Confluence and **no administration rights**.
2. Give it **Browse projects** on the Jira projects LEKA should read, and
   **View** on the Confluence spaces, nothing more. What it cannot see,
   LEKA cannot see: issue security levels, project permissions, space
   permissions and page restrictions apply to LEKA as to anyone.
3. Signed in as that account, create a token at
   [id.atlassian.com → Security → API tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
   Give it an expiry date.
4. In LEKA, **Sources → Add → Jira** (or **Confluence**): the site, the
   account's email, the token. Test, choose the projects or the spaces,
   activate.

An account that can administer Jira is accepted, and the Jira test says so
in its warnings. Tokens with scopes (Atlassian's newer kind), Jira Data
Center and Confluence Data Center are not supported: each is another API.

## Jira

| | |
|---|---|
| Credentials | `token` (write-only, first so the stored hint is the token's), `email` of the account |
| Config | `site`, `projects` |
| Category | `project` |
| Capabilities | `projects`, `issues` |

### Scope

`projects` takes project keys — `PAY`, `OPS` — in capitals (typed in small
letters, they are kept in capitals). Absent, the source reads every project
the account can browse. The Sources screen offers the choices from
`GET /sources/{id}/scope/options`, at most 1 000, each with its
description and when an issue in it last changed. The connection test
fails with `NOT_FOUND`, naming them, when Jira does not show the account a
project in scope.

### The connection test

1. `GET /rest/api/3/myself` — the account, and its time zone.
2. `GET /rest/api/3/mypermissions?permissions=ADMINISTER` — a warning if the
   account administers Jira; no answer is not a failure.
3. `GET /rest/api/3/project/search?keys=…` — every project in scope is there.
4. One page of projects: `projects_visible` in the source's metadata.
5. One JQL search on a project in scope: `issues` if the account may search.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `projects` | each project, with its description and last activity | whole each pass |
| `issues` | each issue with every field — comments, links to other issues, parent, sprint, custom fields | JQL `updated >=` the last pass |

Issues are asked **one project at a time** (`project = "PAY" ORDER BY
updated ASC`), so a search is always bounded and every record knows its
project (`container`). They are known by Jira's numeric id, which survives
a move to another project; the key (`PAY-12`) is in the payload.

An incremental pass needs care: JQL reads a date **to the minute, in the
account's time zone**. LEKA reads the zone at the start of the pass
(`/myself`), converts, and asks from a minute earlier. When Jira does not
say the zone, it asks from fourteen hours earlier — the widest offset there
is. An issue read twice is a write, never a duplicate: the sync engine
keeps the latest version of each id.

### Limits

- **Quota**: Atlassian's, per account. An exhausted quota is `RATE_LIMITED`
  with the time to wait (`Retry-After`); health turns `degraded` when
  Atlassian says the quota is nearly spent (`X-RateLimit-NearLimit`).
- **Pagination**: projects follow Jira's `nextPage`, and only on the site;
  issues follow `nextPageToken`. A token Jira repeats ends the pass with
  `PROVIDER_ERROR` rather than loop.

## Confluence

| | |
|---|---|
| Credentials | `token` (write-only, first), `email` of the account — the same pair as Jira's |
| Config | `site`, `spaces` |
| Category | `docs` |
| Capabilities | `spaces`, `pages` |

### Scope

`spaces` takes space keys as Confluence writes them — `ENG`, or a personal
space's `~5b10ac8d…` — and keeps them as typed. Absent, the source reads
every space the account can see. The choices come from
`GET /sources/{id}/scope/options`, at most 1 000, with each space's
description. The connection test fails with `NOT_FOUND`, naming them, when
Confluence does not show the account a space in scope.

### The connection test

1. `GET /wiki/rest/api/user/current` — the account (API v2 has no such
   call). An anonymous answer is a refused sign-in.
2. `GET /wiki/api/v2/spaces?keys=…` — every space in scope is there.
3. One page of spaces: `spaces_visible` in the source's metadata (`"50+"`
   when there are more).
4. One page of a space in scope: `pages` if the account may read them.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `spaces` | each space, with its plain-text description | whole each pass |
| `pages` | each current page with its body in Confluence's storage format (XHTML), its parent, its version | most recently changed first, stops at the last pass |

Pages are read **one space at a time**, sorted by Confluence by the date of
their latest version (`sort=-modified-date`). An incremental pass stops at
the first page changed before the last one — safe here, because the order
is Confluence's own and follows that very date. Pages are known by
Confluence's id; the space's key is their `container`.

A page the account may not view, restricted pages included, is not in
Confluence's answers, so it is not in LEKA's. Not read yet: blog posts,
comments, attachments, archived pages.

### Limits

- **Quota**: Atlassian's, as for Jira: `RATE_LIMITED` with `Retry-After`,
  `degraded` health on `X-RateLimit-NearLimit`.
- **Pagination**: Confluence's next-page links are relative
  (`/wiki/api/v2/…?cursor=…`). They are read against the site, and a link
  that would leave it — another host, or plain `http` — is refused.

## Diagnostics

| Jira or Confluence answers | Diagnostic |
|---|---|
| a redirect | `NOT_FOUND` — no such Atlassian Cloud site |
| Confluence: an anonymous user | `AUTH_INVALID` |
| 401 | `AUTH_INVALID` — the email or the token; Atlassian does not say which |
| 403 naming a scope | `INSUFFICIENT_SCOPE` |
| 403 | `PERMISSION_DENIED` |
| 404 | `NOT_FOUND`, naming what was missing |
| 429 | `RATE_LIMITED`, with `retry_after` |
| 5xx | `PROVIDER_ERROR` |

The token is removed from every detail, and so is anything shaped like an
`Authorization` header.
