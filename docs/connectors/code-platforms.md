# Code platforms — what LEKA asks for, and what it reads

GitHub, GitLab and Bitbucket, through [the connector framework](framework.md). LEKA-345.
**LEKA only reads**: every call is a GET, and the least a token needs is
below. A token that can do more is accepted, and the connection test says so
in its warnings.

---

## GitHub

| | |
|---|---|
| Token | fine-grained personal access token |
| Repository access | the repositories LEKA should read, or all of them |
| Permissions, all **read-only** | Metadata, Contents, Pull requests, Issues, **Deployments** — and, to read the organisation's teams, **Members** (organisation permission) |
| Config | `organization` (empty: the token owner's repositories), `base_url` for GitHub Enterprise Server, `repositories` |

A classic token works too (`read:org` for the teams); one with `repo`,
`workflow`, `admin:*` or any `write:*` scope draws a warning.

**Teams** (`teams`, LEKA-365), with an `organization`: each team — name,
description, privacy, its parent team — with its **maintainers** and its
**members**, by login (`GET /orgs/{org}/teams`, then
`…/teams/{slug}/members?role=maintainer|member`: two calls a team), whole
each pass. A token without the Members permission leaves them out at the
connection test — never a failure. A team's maintainers lead it in the
company model ([company-model.md § 12](../company-model.md)).

**Deployments** (`deployments`, LEKA-367): each repository's, newest first
(`GET /repos/{repo}/deployments`) — those of the last 90 days at the first
pass, then those made since the last pass less a day — each with its
statuses (`…/deployments/{id}/statuses`: one call a deployment): how it
went, and when. A token without the Deployments permission leaves them out
at the connection test; an existing source reads them after its next test.
In the model: what shipped where, and what changed before an incident
([company-model.md § 14](../company-model.md)).

## GitLab

| | |
|---|---|
| Token | personal, group or project access token |
| Scope | `read_api` — nothing else |
| Role | Reporter, on the group or the projects LEKA should read |
| Config | `group` with its subgroups (empty: the projects the token's owner is a member of), `base_url` for a self-managed GitLab, `projects` |

**Deployments** (`deployments`, LEKA-367): each project's, those updated
since the last pass — the last 90 days at the first
(`GET /projects/{id}/deployments?order_by=updated_at&updated_after=…`) —
with their environment and tier, commit, user, job and pipeline. A project
whose environments are switched off is not asked.

A token with `api`, `write_repository`, `write_registry`, `sudo` or
`admin_mode` draws a warning. When GitLab says when the token expires, the
test records it (`token_expires_at` in the source's metadata).

## Bitbucket

Bitbucket Cloud only — Data Center is another API.

| | |
|---|---|
| Token | a repository, project or workspace access token (sent as Bearer), or an Atlassian API token with its account's `email` (sent as Basic) |
| Scopes, all **read** | Repositories, Pull requests, Issues; for an API token also `read:workspace:bitbucket` |
| Config | `workspace` (required), `repositories` |

App passwords are retired by Atlassian and are not offered. An access token
is not a user: the source is then named by its workspace. A token Bitbucket
reports as able to write draws a warning.

## What the code says it runs (`components`, LEKA-369)

GitHub, for now. Each repository's default branch: its tree, **one read**
(`GET /repos/{repo}/git/trees/{branch}?recursive=1`), then the files that
say what it runs, **one read each**, `MAX_FILES` (40) at most, none above
200 KB, none in a dependency, a build or a test (`node_modules`, `vendor`,
`tests`, `fixtures`…): compose files, CI workflows, env examples, proxy
configs (Caddy, nginx) first, then code manifests (`package.json`,
`pyproject.toml`, `requirements*.txt`, `go.mod`), then Dockerfiles. The
token's **Contents** permission — already asked for — reads them; the
connection test probes it.

What they declare (`leka/connectors/components.py`, pure, local — no model,
no paid service) becomes one record per component, whole each pass:

| Component | Read from |
|---|---|
| a **service** of the code — an API, a web app, a worker, a scheduler, a one-off job — and a proxy in front of them (Caddy, nginx, Traefik…) | a compose file's services: built from the repository (`build`, or an image a workflow builds from a directory) or a known proxy image; its language and framework from its code's manifests — a worker's queue framework (RQ, Celery), not its web one; where it is reached from the proxy's address for it |
| a **database**, a cache, a queue | a compose service of a known image (PostgreSQL, Redis, RabbitMQ…); a connection URL in a service's settings — its value, or the example its comment gives |
| an object **store** | `…OBJECT_STORE=s3`, its region |
| a **service outside** | a configured value: an SMTP host (its provider: OVH, SendGrid…), a Sentry DSN, a Stripe or OpenAI key — an empty one is off |

And the links between them, each named, with the file and the line:
`routes` (a proxy to a service), `calls` (a front end told its API's URL),
`queue`, `cache`, `stores`, `files`, `email`, `uses`, `depends` (a
`depends_on` — waiting for a one-off job is not one). What a workflow
deploys, to which environment and how (`appleboy/ssh-action`…), is said of
the components of the compose file it ships.

**Never guessed.** A library is not a database: an API carrying `pymongo`
to read its customers' MongoDB keeps nothing in MongoDB. A store comes
from configuration only, a service outside from a configured value. When
a compose file is named for production, the others — a development
compose's test databases — are not read.

**Where it answers.** A service reached at a public URL — `api.leka-core.com`
— has its name resolved as the repository is read: the server's own
resolver, 3 s at most, public addresses only (`public_addresses`). Nothing
connects to it. Which cloud machine has that address, and so runs it, is
enrichment's ([enrichment.md § 7, Architecture](../enrichment.md)).

**Cost.** One read for the tree and one per file chosen, for each
repository, at each pass: some forty an hour per repository — and a DNS
lookup per public name. An existing
source reads components after its next connection test.

## Scope

`repositories` (GitHub, Bitbucket) and `projects` (GitLab) take full paths
— `acme/api`, `acme/platform/api` — inside the configured organisation,
group or workspace. Absent, the source reads everything the token sees. The Sources
screen offers the choices from `GET /sources/{id}/scope/options`, at most
1 000. The connection test probes a repository in scope and fails with
`NOT_FOUND` when the platform does not show it.

## What is read

| Capability | GitHub | GitLab | Bitbucket | Incremental |
|---|---|---|---|---|
| `repositories` | repositories | projects | repositories | whole each pass |
| `branches` | branches | branches | branches | whole each pass |
| `commits` | default branch | default branch | main branch | GitHub, GitLab: filtered by the platform. Bitbucket: roughly newest first — older commits are skipped, and the listing ends after a page with nothing newer (a rebase can put an old date ahead) |
| `pull_requests` | pull requests | merge requests | pull requests | GitHub, Bitbucket: newest-updated first, stops at the last pass. GitLab: `updated_after` |
| `issues` | issues, without pull requests | issues | issues, where the tracker is on | GitHub, GitLab: filtered by the platform. Bitbucket: newest-updated first, stops |
| `releases` | releases | releases | — (Bitbucket has none) | whole each pass |

Every state is read — open, merged, closed. A capability the token cannot
read is left out at the test (`capabilities` on the source), not failed
later. GitLab skips what a project has switched off (issues, merge
requests, releases, the repository) and the commits and branches of an
empty repository. The engine that runs the synchronisation is LEKA-352.

Records are known by the platform's own ids, stable across renames:
GitHub's `node_id`; GitLab's numeric ids, prefixed with the project's for
what has none of its own (`11:main`, `11:<sha>`, `11:v1.2`); Bitbucket's
repository `uuid`, and that uuid before what lives in it (`{…}:main`,
`{…}:<hash>`, `{…}:7`).

## Limits

- **Quota**: GitHub 5 000 calls an hour per token; GitLab.com's limits per
  user, self-managed as configured; Bitbucket Cloud's per hour, per token.
  An exhausted quota is `RATE_LIMITED` with the time to wait. A bulk read
  stops itself earlier, when less than 10 % is left, so the customer's own
  tools keep a reserve on a token they share with LEKA. Health turns
  `degraded` below a tenth of the quota (GitHub, GitLab), or when Bitbucket
  says it is near its limit.
- **Pagination** follows the platform's `Link` header (GitHub, GitLab) or
  the `next` of the body (Bitbucket), and only to the host configured: a
  link elsewhere is refused, so the token never leaves it.
