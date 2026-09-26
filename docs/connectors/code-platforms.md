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
| Permissions, all **read-only** | Metadata, Contents, Pull requests, Issues |
| Config | `organization` (empty: the token owner's repositories), `base_url` for GitHub Enterprise Server, `repositories` |

A classic token works too; one with `repo`, `workflow`, `admin:*` or any
`write:*` scope draws a warning.

## GitLab

| | |
|---|---|
| Token | personal, group or project access token |
| Scope | `read_api` — nothing else |
| Role | Reporter, on the group or the projects LEKA should read |
| Config | `group` with its subgroups (empty: the projects the token's owner is a member of), `base_url` for a self-managed GitLab, `projects` |

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
| `commits` | default branch | default branch | main branch | GitHub, GitLab: filtered by the platform. Bitbucket: newest first, stops at the last pass |
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
  An exhausted quota is `RATE_LIMITED` with the time to wait. Health turns
  `degraded` below a tenth of the quota (GitHub, GitLab), or when Bitbucket
  says it is near its limit.
- **Pagination** follows the platform's `Link` header (GitHub, GitLab) or
  the `next` of the body (Bitbucket), and only to the host configured: a
  link elsewhere is refused, so the token never leaves it.
