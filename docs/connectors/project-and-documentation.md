# Project and documentation tools — what LEKA asks for, and what it reads

Jira, Confluence, Linear, Notion, Asana, Trello, ClickUp, Monday, Slab,
Guru, Google Workspace and Microsoft 365, through
[the connector framework](framework.md). LEKA-346. **LEKA only reads**: Jira
and Confluence are read with GETs, to the customer's Atlassian Cloud site
and nowhere else; Linear, Monday and Slab, which speak only GraphQL, with
`query` documents sent by POST to their one endpoint — never a mutation;
Notion with GETs, and its search, which it offers only as a POST; Asana,
Trello, ClickUp and Guru with GETs; Google Workspace and Microsoft 365 with
GETs under read-only permissions, their one POST being the token
exchange.

**A personal token can do what its owner can.** Asana, ClickUp, Monday and
Linear cannot narrow a personal token to reading; Trello can. For each, the
boundary is the account the token belongs to: create a **dedicated member**
— not an owner, not an admin — in the projects, boards or spaces LEKA
should read, and nothing more. What that member cannot see, LEKA cannot
see. The connection test warns when the token belongs to an admin
(Linear, ClickUp, Monday).

**What the documentation tools' records become** (LEKA-366): each space,
Notion database, topic, collection and drive a **knowledge space**; each
page, post, card and file a **document** in it — its author, owner and last
editor, what it links to, how fresh it is, what it describes. Nothing more
is asked of the tools: the same payloads, read further
([company-model.md § 13](../company-model.md)).

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

## Asana

| | |
|---|---|
| Endpoint | `https://app.asana.com/api/1.0` — fixed, nothing to configure |
| Credentials | `token`, a personal access token (write-only), sent as Bearer |
| Config | `projects` |
| Category | `project` |
| Capabilities | `projects`, `issues` (Asana's tasks) |

### What to create at Asana

Signed in as the dedicated member, **My settings → Apps → Developer apps →
Create new token**. The token sees every workspace and project its member
sees; Asana cannot make it read-only.

### Scope

`projects` takes project gids — `1204567890123456` — or a pasted link to
the project (`https://app.asana.com/1/<workspace>/project/<gid>/…`, or the
older `https://app.asana.com/0/<gid>/…`), kept as the gid. Absent, the
source reads every project of every workspace the member belongs to. The
choices come from `GET /sources/{id}/scope/options`: every project of every
workspace, archived ones too (said in the description), at most 1 000. The
connection test fails with `NOT_FOUND`, naming them, when Asana does not
show a project in scope.

### The connection test

1. `GET /users/me` — the account, and its workspaces.
2. `GET /projects/{gid}` for each project in scope, at once.
3. One page of projects of the first workspace: `projects_visible`.
4. One project and one page of its tasks: `projects` and `issues`.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `projects` | each project, archived ones too — notes, owner, team, dates, status | whole each pass |
| `issues` | each task of each project — notes, assignee, sections, tags, custom fields, parent, subtasks' count | `modified_since` the last pass, filtered by Asana |

A task in several projects is read once per pass, under the first project
that holds it (its `container`); its `memberships` list them all. Not read
yet: subtasks that sit in no project, comments (stories), attachments,
dependencies (a feature of paid plans).

### Limits

- **Quota**: Asana's requests per minute, per token; a refusal is
  `RATE_LIMITED` with `Retry-After`. Asana sends no quota headers, so
  health is `healthy` or failed.
- **Pagination**: Asana's `offset`, sent back with the same query.
- **Errors**: 401 → `AUTH_INVALID`, 402 (a paid plan's feature) and 403 →
  `PERMISSION_DENIED`, 404 → `NOT_FOUND`, 429 → `RATE_LIMITED`, 5xx →
  `PROVIDER_ERROR`.

## Trello

| | |
|---|---|
| Endpoint | `https://api.trello.com/1` — fixed, nothing to configure |
| Credentials | `token` (write-only, first so the stored hint is the token's), `api_key` of a Power-Up (write-only) |
| Config | `boards` |
| Category | `project` |
| Capabilities | `projects` (boards), `issues` (cards) |

### What to create at Trello

1. Signed in as the dedicated member, at
   [trello.com/power-ups/admin](https://trello.com/power-ups/admin), create a
   Power-Up (any workspace) and generate its **API key**.
2. Authorise a token for that key, **read only** and without expiry or
   with the one you choose:
   `https://trello.com/1/authorize?key=<key>&scope=read&expiration=never&name=LEKA&response_type=token`.
3. In LEKA, **Sources → Add → Trello**: the token and the key.

The key and the token go in the `Authorization` header, never in a URL:
the HTTP client writes every URL it calls to the logs. Trello tells what a
token may do only at a URL holding the token (`/tokens/{token}`), so the
connection test does not ask, and cannot warn about a token that may
write: authorising it with `scope=read`, as above, is what keeps it to
reading.

### Scope

`boards` takes board ids (24 hexadecimal digits), short links (`AbCd1234`)
or pasted links (`https://trello.com/b/AbCd1234/roadmap`), kept as the id
or the short link. Absent, the source reads every board of the member,
closed ones too. The choices come from `GET /sources/{id}/scope/options`:
every board of the member, closed ones said so.

### The connection test

1. `GET /members/me` — the member.
2. `GET /members/me/boards` — once: Trello allows only 100 calls to
   `/members/` every fifteen minutes. Every board in scope must be there;
   `boards_visible` counts the open ones.
3. One open board and one of its cards: `projects` and `issues`.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `projects` | each board with its lists, labels, members and workspace | whole each pass |
| `issues` | each card, archived ones too — list, labels, members, dates, due | every card read, those active since the last pass kept |

Cards are read board by board, newest first, 500 a page, the next page
being the cards created `before` the last one read. Trello cannot filter
cards by their last activity, so an incremental pass reads them all and
keeps those whose `dateLastActivity` is after the last pass, less two
minutes. A card deleted leaves at the weekly full pass. Not read yet:
comments and other actions, checklists, attachments, custom fields.

### Limits

- **Quota**: 100 requests every 10 seconds per token. A refusal is
  `RATE_LIMITED`, with the length of Trello's window as the wait; health
  reads `x-rate-limit-api-token-*` and turns `degraded` under a tenth left.
- **Errors**: Trello answers in plain text. `invalid token` or `invalid
  key` → `AUTH_INVALID`, `unauthorized … permission requested` →
  `PERMISSION_DENIED`, 404 → `NOT_FOUND`, 429 → `RATE_LIMITED`.

## ClickUp

| | |
|---|---|
| Endpoint | `https://api.clickup.com/api/v2` — fixed, nothing to configure |
| Credentials | `token`, a personal token (`pk_…`, write-only), sent as it is |
| Config | `spaces` |
| Category | `project` |
| Capabilities | `projects` (Lists), `issues` (Tasks) |

### What to create at ClickUp

Signed in as the dedicated member, **Settings → Apps → API Token →
Generate**. ClickUp nests Workspaces, Spaces, Folders, Lists and Tasks; the
token sees the Workspaces and the Spaces its member sees.

### Scope

`spaces` takes Space ids — `90123456`. Absent, the source reads every Space
of every Workspace the token sees. The choices come from
`GET /sources/{id}/scope/options`, private Spaces said so.

### The connection test

1. `GET /user` — the account.
2. `GET /team` — its Workspaces, and its role in each: a warning for an
   owner or an admin.
3. `GET /team/{id}/space` — every Space; every Space in scope must be there.
4. One Space's Lists and one page of its Tasks: `projects` and `issues`.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `projects` | each List, in a Folder (said in `folder`) or not | whole each pass |
| `issues` | each Task, closed ones and subtasks too — status, assignees, tags, custom fields, dependencies, description in Markdown | `date_updated_gt` the last pass, filtered by ClickUp |

Tasks are asked Workspace by Workspace, for the Spaces in scope
(`/team/{id}/task?space_ids[]=…`), 100 a page in the order they were
created — an order an edit during the pass cannot shuffle. Their List is
their `container`. Not read yet: comments, docs, archived Lists.

### Limits

- **Quota**: 100 requests a minute per token on most plans. A refusal is
  `RATE_LIMITED`, with the time until `X-RateLimit-Reset`; health turns
  `degraded` under a tenth left.
- **Errors**: ClickUp's `ECODE` first: `OAUTH_023`, `026`, `027`, `029`–`045`
  (a Workspace not authorised for the token) → `PERMISSION_DENIED`; any
  other 401 → `AUTH_INVALID`; 404 → `NOT_FOUND`.

## Monday

| | |
|---|---|
| Endpoint | `POST https://api.monday.com/v2`, `API-Version: 2026-07` — fixed, nothing to configure |
| Credentials | `token`, a personal API token (write-only), sent as it is |
| Config | `boards` |
| Category | `project` |
| Capabilities | `projects` (boards), `issues` (items) |

### What to create at Monday

Signed in as the dedicated member (not an admin), **avatar → Developers →
API token → Show**. The token can do what its member can; Monday cannot
narrow it.

### LEKA reads, over POST

Like Linear: Monday answers GraphQL only. The client may POST to `/v2` and
nowhere else; every document is a constant in `monday/connector.py` and a
`query`, checked before sending and by a test over all of them; the
stand-in Monday fails on anything else. The API version is pinned, so
Monday's next version cannot change an answer under LEKA.

### Scope

`boards` takes board ids or pasted links
(`https://acme.monday.com/boards/1234567890`), kept as the id. Absent, the
source reads every active board the token sees. Monday lists subitem
boards and docs as boards too; LEKA offers and reads boards only.

### The connection test

1. `me` — the account, whether it administers it.
2. The boards in scope (`boards(ids: …)`), or one page of boards:
   `boards_visible`.
3. One item of one board: `issues`.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `projects` | each board with its workspace, owners, groups and columns | whole each pass |
| `issues` | each item with its group, creator, column values (text and raw value) and subitems | every item read, those updated since the last pass kept |

Items are read board by board with Monday's cursors (`items_page`, then
`next_items_page`), 100 a page. Monday filters items by date only through
a rule per board, so an incremental pass reads them all and keeps those
updated after the last pass, less two minutes. Not read yet: updates
(comments), archived boards, docs.

### Limits

- **Budget**: Monday's complexity points per minute. A refusal —
  `COMPLEXITY_BUDGET_EXHAUSTED`, `RATE_LIMIT_EXCEEDED`, a 429 — is
  `RATE_LIMITED`, with Monday's `retry_in_seconds`.
- **Errors**: Monday refuses with a 200 and `errors` as often as with an
  HTTP error, and an older form (`error_code`) still appears. All become
  the same diagnostics: `Unauthorized` → `AUTH_INVALID`,
  `UserUnauthorizedException` → `PERMISSION_DENIED`,
  `ResourceNotFoundException`, `InvalidBoardIdException` → `NOT_FOUND`.

## Slab

| | |
|---|---|
| Endpoint | `POST https://api.slab.com/v1/graphql` — fixed, nothing to configure |
| Credentials | `token`, the workspace's API token (write-only), sent as it is |
| Config | `topics` |
| Category | `docs` |
| Capabilities | `spaces` (topics), `pages` (posts) |

### What to create at Slab

Slab's API belongs to its **Business and Enterprise** plans. A workspace
admin copies the token from **Team settings → Developer**. The token reads
as the **Slab Bot**: it sees the topics and posts the bot was given, and no
more — that is the boundary. Give the bot access to what LEKA should read,
and to nothing secret.

### LEKA reads, over POST

Like Linear and Monday: the client may POST to `/v1/graphql` and nowhere
else; every document is a constant in `slab/connector.py` and a `query`,
checked before sending and by a test over all of them.

### Scope

`topics` takes topic ids. Absent, the source reads every post the bot sees.
The choices come from `GET /sources/{id}/scope/options`: every topic, with
its description as text. The connection test fails with `NOT_FOUND`,
naming them, when the bot does not see a topic in scope.

### The connection test

1. `organization` — its name is the account.
2. Its topics — every topic in scope must be there — and its posts:
   `topics_visible`, `posts_visible`.
3. One post, content included: `pages` if Slab answers. A bot that sees
   nothing passes, with a warning saying how to give it access.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `spaces` | each topic, with its description | whole each pass |
| `pages` | each post with its content (Quill delta, as JSON), title, dates, link access | the list whole; the content of those updated since the last pass, less two minutes |

Slab gives a post's content only one post at a time, so a pass lists the
posts, then asks each one it needs. With `topics`, a post is read when one
of its topics is in scope, and that topic is its `container`.

### Limits

- **Pace**: Slab does not publish its limit; the client keeps to four
  requests a second. A refusal for the rate — a 429, or an error that says
  so — is `RATE_LIMITED`.
- **Errors**: Slab's errors have no code. A 401 or an error saying
  "unauthorized" → `AUTH_INVALID`; "forbidden" → `PERMISSION_DENIED`
  (often: the plan has no API); "not found" → `NOT_FOUND`.

## Guru

| | |
|---|---|
| Endpoint | `https://api.getguru.com/api/v1` — fixed, nothing to configure |
| Credentials | `token` (write-only, first so the stored hint is the token's), `username` — HTTP Basic |
| Config | `collections` |
| Category | `docs` |
| Capabilities | `spaces` (collections), `pages` (cards) |

### What to create at Guru

Two kinds of token fit, from **Settings → API Access**:

- **A collection token** — read-only by Guru's own design, for one
  collection. Its username is the collection's id. The narrowest, and the
  one to prefer.
- **A user token** — its username is the user's email; it can do what the
  user can. Then use a dedicated user with read access only to the
  collections LEKA should read.

### Scope

`collections` takes collection ids, kept in small letters. Absent, the
source reads every collection the token sees. The choices come from
`GET /sources/{id}/scope/options`.

### The connection test

1. `GET /whoami` — the account: a user's email, or a collection's name.
2. `GET /collections` — every collection in scope must be there:
   `collections_visible`.
3. One search of cards: `pages` if Guru answers.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `spaces` | each collection | whole each pass |
| `pages` | each card — title, content (HTML), collection, verification state, dates | most recently modified first, stops at the last pass less two minutes |

Cards come from `GET /search/query`, sorted by Guru on `lastModified`,
newest first, 50 a page. Guru pages with a `Link` header whose relation is
`next-page`, not `next`; the link is followed only on Guru's host. With
`collections`, a card is read when its collection is in scope, and that
collection is its `container`. Archived cards are not read.

### Limits

- **Quota**: a refusal for the rate is `RATE_LIMITED`, with `Retry-After`.
  Guru sends no quota headers, so health is `healthy` or failed.
- **Errors**: 401 → `AUTH_INVALID` (the username or the token), 403 →
  `PERMISSION_DENIED`, 404 → `NOT_FOUND`, 5xx → `PROVIDER_ERROR`.

## Office suites: a file and its text

Google Workspace and Microsoft 365 hold files, not records. Each file is
read with its metadata and, where one can be had, its **text**
(`content`, and `content_truncated` when it was cut):

- Google Docs and Slides, exported by Google as plain text; Google Sheets
  as CSV — the first sheet only, as Google exports it;
- Word, Excel and PowerPoint files (`.docx`, `.xlsx`, `.pptx`) and plain
  text (`.txt`, `.md`, `.csv`), downloaded and read by
  `leka/connectors/office.py` — the words in reading order, paragraph by
  paragraph, slide by slide, row by row;
- anything else — PDFs, images, older `.doc` files — without text.

A file larger than 10 MB is read without its text, and a text is kept to
1 MB. `office.py` never parses the XML (the text is taken from the
elements that hold it, so no entity is expanded and nothing is fetched)
and never unzips more than 50 MB of an archive, whatever it claims. A file
the vendor will not hand over — too large to export, downloads disabled —
is a file without text, not a failed pass; a quota reached is.

## Google Workspace

| | |
|---|---|
| Endpoint | `https://www.googleapis.com/drive/v3` — fixed, nothing to configure |
| Credentials | `service_account_key`, a service account's JSON key (write-only) |
| Config | `subject` (optional), `drives` |
| Category | `docs` |
| Capabilities | `drives` (shared drives), `files` |

### What to create at Google

1. In a Google Cloud project, **enable the Google Drive API**, create a
   **service account** and download a **JSON key** for it.
2. Then either:
   - **share with the service account** — its address,
     `…@….iam.gserviceaccount.com` — the folders and shared drives LEKA
     should read, as with any colleague. It sees those, and only those.
     Leave `subject` empty.
   - or, to read what a user sees, have a Workspace super admin grant the
     service account **domain-wide delegation** (Admin console → Security
     → API controls → Domain-wide delegation) for exactly one scope,
     `https://www.googleapis.com/auth/drive.readonly`, and put in `subject`
     the email of a **dedicated, read-only account** that is a member of
     what LEKA should read.
3. In LEKA, **Sources → Add → Google Workspace**: the key, and `subject` if
   delegation was chosen. Test, choose the drives, activate.

**The directory** (`people`, LEKA-365) — each user's name, address,
title, department, organisational unit and manager — needs the delegation
to list a second scope, `https://www.googleapis.com/auth/admin.directory.user.readonly`,
and a `subject` who may read the directory (an admin, or a delegated
read-only admin role). Without them, `people` is left out at the
connection test, with a warning naming the scope: Drive is read as before.

The token is always asked for `drive.readonly`: whoever the account acts
as, it cannot write. A delegation that does not list that scope, or a
`subject` outside the domain, is refused by Google — the test says
`PERMISSION_DENIED`, naming the delegation.

### Scope

`drives` takes `user` — My Drive and what is shared with the account (the
service account's, or the `subject`'s) — and shared drive ids, typed or
pasted as a link (`https://drive.google.com/drive/folders/0A…`). Absent,
the source reads My Drive and every shared drive the account is a member
of. The choices come from `GET /sources/{id}/scope/options`. The
connection test fails with `NOT_FOUND`, naming them, when the account is
not a member of a shared drive in scope.

### The connection test

1. A token (`leka/connectors/google.py`, shared with the Google Cloud
   connector), under `drive.readonly`, as `subject` if set.
2. `GET /about` — the account.
3. `GET /drives` — the shared drives; every one in scope must be there.
4. One page of files of the first corpus: `files_visible`. Nothing visible
   is a pass with a warning saying what to share with which address.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `drives` | each shared drive | whole each pass |
| `files` | each file — not folders, not the trash — with owners, last modifier, link, and its text | `modifiedTime >` the last pass less two minutes, filtered by Drive |
| `people` | each user of the domain — name, primary address, title and department (their primary organisation), organisational unit, whether suspended, their manager (`relations`, by address) — from the Admin SDK's Directory API (`GET admin/directory/v1/users?customer=my_customer`), its own token | whole each pass |

Files are listed one corpus at a time — My Drive, then each shared drive —
rather than with Drive's `allDrives`, which may answer incompletely. A file
listed twice is read once. Its shared drive (or `user`) is its
`container`.

### Limits

- **Quota**: Drive's per-user quotas. A 429, or a 403 whose reason is
  `rateLimitExceeded` or `userRateLimitExceeded`, is `RATE_LIMITED`.
- **Errors**: Drive's error `reason` first — `accessNotConfigured` → the
  Drive API is off in the service account's project (`PERMISSION_DENIED`,
  said so); 401 → `AUTH_INVALID`; 404 → `NOT_FOUND`.

## Microsoft 365

| | |
|---|---|
| Endpoint | `https://graph.microsoft.com/v1.0` — fixed, nothing to configure |
| Credentials | `client_id` (first, so the stored hint names the application), `client_secret` (write-only) |
| Config | `tenant_id`, `drives` |
| Category | `docs` |
| Capabilities | `drives` (SharePoint document libraries, OneDrives), `files` |

### What to create at Microsoft

1. In the Microsoft Entra admin center, **App registrations → New
   registration** (single tenant). Note its **Application (client) ID** and
   the **Directory (tenant) ID**.
2. **API permissions → Microsoft Graph → Application permissions**:
   `Sites.Read.All`, `Files.Read.All` and — to read the users' OneDrives —
   `User.Read.All`. Nothing with *Write*. Then **Grant admin consent**.
3. **Certificates & secrets → New client secret**, with an expiry date.
4. In LEKA, **Sources → Add → Microsoft 365**: the tenant id, the client id,
   the secret. Test, choose the drives, activate.

These application permissions let the application read every site and
every OneDrive of the tenant; the drives chosen in LEKA are what it reads.

### Scope

`drives` takes Graph drive ids (`b!…`). Absent, the source reads every
site's document libraries and, with `User.Read.All`, every user's OneDrive.
The choices come from `GET /sources/{id}/scope/options` — "site —
library" and "user — OneDrive" — within 300 calls to Graph; a larger
tenant's listing says it was cut. The connection test fails with
`NOT_FOUND`, naming them, when Graph does not show a drive in scope.

### The connection test

1. A token (`leka/connectors/microsoft.py`, shared with the Azure
   connector) for Microsoft Graph.
2. `GET /sites/root` — the tenant's SharePoint host is the account.
3. `GET /drives/{id}` for each drive in scope.
4. `GET /users` — without `User.Read.All`, a warning: the OneDrives and
   the directory are left out, SharePoint is read.
5. One page of the first drive: `files`.

### What is read

| Capability | What | Incremental |
|---|---|---|
| `drives` | each document library and OneDrive | whole each pass |
| `files` | each file — not folders, not OneNote notebooks, not deleted items — with its path, author, last modifier, link, and its text | Graph's delta from the last pass less two minutes |
| `people` | the directory (LEKA-365): each user — name, address (`mail`, else the sign-in name), title, department, office, whether their account is on, guest or member — **with their manager**, expanded on the listing (`GET /users?$expand=manager`), under the same `User.Read.All` | whole each pass |

Files are read drive by drive through `/drives/{id}/root/delta`: every item
on an initial pass, and on an incremental one from a time — SharePoint and
OneDrive for Business take a timestamp in place of a delta token. An item
delta gives twice is read once. Its drive is its `container`.

A file's bytes are not at Graph: `…/content` answers 302 with a
pre-authenticated link on the tenant's SharePoint host. LEKA follows it
only to a SharePoint host (`*.sharepoint.com`, and Microsoft's national
clouds), over https, without its own token — the link carries its own. The
HTTP client no longer writes the URLs it calls to the logs, so that link
never reaches them.

### Limits

- **Throttling**: a 429 or a 503 with `Retry-After` is `RATE_LIMITED`.
- **Errors**: 401 → `AUTH_INVALID`; 403 → `PERMISSION_DENIED`, naming the
  permissions to grant; 404 → `NOT_FOUND`. At sign-in, Microsoft identity's
  codes: `AADSTS90002` (no such tenant) → `NOT_FOUND`, `AADSTS7000222` (an
  expired secret) → `AUTH_EXPIRED`.

## What comes after

Every capability of these tools has an extraction strategy
([extraction.md](../extraction.md)): a title, the text — a page's body read
out of its markup, a file's text — the dates, the people, the project or the
parent. Normalisation ([normalisation.md](../normalisation.md)) makes their
projects `project`, their issues, tasks, cards and items `issue` — Linear's
by their identifier, with the alias `ticket:ENG-42` — and their pages, posts,
cards and files `document`; spaces, databases, topics, collections and
drives stay containers. Confluence's pages and spaces carry `web_url`, the
link to open them (Confluence gives a path only).

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
`Authorization` header — or like a Linear key (`lin_api_…`), a Notion
secret (`ntn_…`, `secret_…`), an Asana token (`2/…:…`), a Trello token
(`ATTA…`), a ClickUp token (`pk_…`) or a JSON Web Token (Monday's),
whoever's it is.
