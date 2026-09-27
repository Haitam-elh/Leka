# Project and documentation tools — what LEKA asks for, and what it reads

Jira, Confluence, Linear and Notion, through
[the connector framework](framework.md). LEKA-346. **LEKA only reads**: Jira
and Confluence are read with GETs, to the customer's Atlassian Cloud site
and nowhere else; Linear, which speaks only GraphQL, with `query` documents
sent by POST to its one endpoint — never a mutation; Notion with GETs, and
its search, which it offers only as a POST.

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

## Linear

| | |
|---|---|
| Endpoint | `POST https://api.linear.app/graphql` — fixed, nothing to configure |
| Credentials | `api_key`, a personal API key (`lin_api_…`, write-only) |
| Config | `teams` |
| Category | `project` |
| Capabilities | `projects`, `issues` |

### What to create at Linear

A personal API key belongs to a person and can do what that person can.
So, as for Atlassian: a dedicated **member** account (not an admin), in the
teams LEKA should read. Signed in as it, **Settings → Security & access →
Personal API keys**: create a key, with **read** access only and limited to
those teams where Linear offers the choice. A key whose owner administers
the workspace is accepted, and the test says so in its warnings.

### LEKA reads, over POST

Linear answers GraphQL only, and GraphQL goes by POST. So Linear is the
first connector to send a body — and the framework makes that narrow:

- the client may POST to `/graphql` and nowhere else (`reads_by_post`);
- every document is a constant in `linear/connector.py`, and is a `query`:
  `read_only()` refuses a `mutation` or a `subscription` before sending,
  and a test runs it over every document;
- the stand-in Linear in the tests fails on anything but a POST of a query
  to `/graphql`.

### Scope

`teams` takes team keys — `ENG`, `OPS` — kept in capitals. Absent, the
source reads every team the key can see. The choices come from
`GET /sources/{id}/scope/options`; the connection test fails with
`NOT_FOUND`, naming them, when Linear does not show a team in scope.

### The connection test

1. `viewer` — the account, its workspace, whether it administers it.
2. `teams(filter: {key: {in: …}})` — every team in scope is there.
3. One page of teams: `teams_visible` in the source's metadata.
4. One project and one issue of a team in scope, asked at once:
   `projects` and `issues` if Linear answers.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `projects` | each project of each team, archived ones too — status, lead, dates, progress, teams | whole each pass; a project shared by teams is read once |
| `issues` | each issue of each team, archived ones too — state, assignee, project, cycle, parent, labels, relations to other issues | `updatedAt >=` the last pass, filtered by Linear |

Issues are asked team by team, and known by Linear's id; the identifier
(`ENG-42`) is in the payload, the team's key is the `container`.

### Limits

- **Quota**: Linear's requests per hour, per key. A refused call says
  `RATELIMITED`, with the time until the hour resets
  (`X-RateLimit-Requests-Reset`); health turns `degraded` under a tenth
  left.
- **Pagination**: Linear's cursors; a cursor Linear repeats ends the pass
  with `PROVIDER_ERROR` rather than loop.
- **Errors**: Linear refuses as often with a 200 and `errors` as with an
  HTTP error. Both become the same diagnostics: `AUTHENTICATION_ERROR` →
  `AUTH_INVALID`, `FORBIDDEN` → `PERMISSION_DENIED`, `…NOT_FOUND` →
  `NOT_FOUND`, `RATELIMITED` → `RATE_LIMITED`, a 5xx → `PROVIDER_ERROR`.

## Notion

| | |
|---|---|
| Endpoint | `https://api.notion.com/v1`, API version `2022-06-28` — fixed, nothing to configure |
| Credentials | `token`, an internal integration's secret (`ntn_…`, write-only) |
| Config | `roots` |
| Category | `docs` |
| Capabilities | `pages`, `databases` |

### What to create at Notion

An internal integration, by a workspace owner:

1. [notion.so/profile/integrations](https://www.notion.so/profile/integrations)
   → **New integration**, type **Internal**, in the workspace LEKA reads.
2. **Capabilities**: tick **Read content** and nothing else — no *Update
   content*, no *Insert content*, no comments, **No user information**.
   Notion's API cannot tell LEKA what was ticked, so this is the only
   place it is decided.
3. Copy the **Internal integration secret**.
4. **Share with it what LEKA may read.** An integration sees nothing until
   a page or a database is shared with it: in Notion, open the page, menu
   **••• → Connections**, add the integration. It then sees that page and
   everything beneath it. This is the boundary — what is not shared, LEKA
   cannot see.
5. In LEKA, **Sources → Add → Notion**: the secret. Test, choose the
   roots, activate.

A test with nothing shared passes with no capability and a warning saying
how to share.

### LEKA reads, one read by POST

Notion lists what it shares only through `POST /search`. The client may
POST to `/search` and nowhere else (`reads_by_post`); every other call is a
GET, and the stand-in Notion in the tests fails on anything else.

### Scope

`roots` narrows what is shared, never widens it: ids of pages and
databases, each read with everything beneath it. The form takes an id,
dashed or not, or a pasted link (`https://www.notion.so/acme/Wiki-1a2b…?v=…`),
and keeps the id as Notion writes it; anything else is refused when the
source is saved. Absent, the source reads everything shared with the
integration.

The choices come from `GET /sources/{id}/scope/options`: the tops of what
is shared — pages and databases whose parent the integration cannot see —
among the 2 000 most recently edited objects, at most 1 000 offered. A
page inside a column block of a shared page is offered too: Notion places
it in the block, not the page. The connection test fails with `NOT_FOUND`,
naming them, when Notion does not share a root.

### The connection test

1. `GET /users/me` — the integration, and its workspace's name.
2. `GET /pages/{id}`, else `GET /databases/{id}` — every root is shared.
3. One search of pages: `pages_visible` in the source's metadata (`"100+"`
   when there are more). One search of databases.
4. `pages` and `databases` for what those searches found.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `pages` | each page — database rows included — with its properties and its blocks | most recently edited first, stops at the last pass less two minutes |
| `databases` | each database, with its properties' schema and description | the same |

Search returns what is shared, most recently edited first. An incremental
pass stops at the first object edited before the last pass **less two
minutes**: Notion rounds `last_edited_time` down to the minute, so a page
edited while the last pass ran can carry a time from before it started.
Read twice is a write, never a duplicate.

A page's content is its blocks, read with `GET /blocks/{id}/children`, in
reading order, each nested block right after the one holding it — three
levels deep and 1 000 blocks at most; `blocks_truncated` says when some
were left out. Child pages and child databases are not read through their
parent: the search finds them as objects of their own. An archived page is
listed without its content.

With `roots`, an object is read only when a root is among its ancestors.
What each object sits in is learned from the search, and what the search
did not show — a database, a block, a page not shared — is asked of Notion
once per pass. An ancestor Notion does not share ends the climb.

Pages and databases are known by Notion's id; the page or database they
sit in is their `container` (none at the top of the workspace).

### Limits

- **Pace**: Notion allows about three requests a second, on average. The
  client keeps to it (one every 0.34 s) rather than be refused halfway;
  a refusal all the same is `RATE_LIMITED` with `Retry-After`. Notion sends
  no quota headers, so health is `healthy` or failed.
- **Pagination**: Notion's cursors; a cursor Notion repeats ends the pass
  with `PROVIDER_ERROR` rather than loop.
- **Errors**: Notion's error `code` first — `unauthorized` →
  `AUTH_INVALID`, `restricted_resource` → `PERMISSION_DENIED` (the
  integration lacks *Read content*), `object_not_found` → `NOT_FOUND`,
  `rate_limited` → `RATE_LIMITED`; a 5xx → `PROVIDER_ERROR`.
- **Not read yet**: comments, files' contents, users' names (the payload
  keeps their ids), deleted pages — those leave with the next full pass.

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
`Authorization` header — or like a Linear key (`lin_api_…`) or a Notion
secret (`ntn_…`, `secret_…`), whoever's it is.
