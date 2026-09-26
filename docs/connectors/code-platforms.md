# Code platforms — what LEKA asks for, and what it reads

GitHub and GitLab, through [the connector framework](framework.md). LEKA-345.
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

## Scope

`repositories` (GitHub) and `projects` (GitLab) take full paths —
`acme/api`, `acme/platform/api` — inside the configured organisation or
group. Absent, the source reads everything the token sees. The Sources
screen offers the choices from `GET /sources/{id}/scope/options`, at most
1 000. The connection test probes a repository in scope and fails with
`NOT_FOUND` when the platform does not show it.

## What is read

| Capability | GitHub | GitLab | Incremental |
|---|---|---|---|
| `repositories` | repositories | projects | whole each pass |
| `branches` | branches | branches | whole each pass |
| `commits` | commits of the default branch | commits of the default branch | filtered by date on the platform's side |
| `pull_requests` | pull requests | merge requests | GitHub: newest-updated first, stops at the last pass |
| `issues` | issues, without pull requests | issues | filtered by date on the platform's side |
| `releases` | releases | releases | whole each pass |

A capability the token cannot read is left out at the test (`capabilities`
on the source), not failed later. GitLab's synchronisation arrives in the
next part of LEKA-345; the engine that runs either is LEKA-352.

## Limits

- **Quota**: GitHub 5 000 calls an hour per token; GitLab.com's limits per
  user, self-managed as configured. An exhausted quota is `RATE_LIMITED`
  with the time to wait; health turns `degraded` below a tenth.
- **Pagination** follows the platform's `Link` header, and only to the host
  configured: a link elsewhere is refused, so the token never leaves it.
