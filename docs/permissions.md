# Permissions

Who may do what, in a workspace. This is the authorisation contract LEKA-331
delivers, and what its Definition of Done means by "authorisation boundaries
are documented".

**This page is checked by a test.** `api/tests/test_permissions_matrix.py`
parses the table below and compares it to `ROLE_PERMISSIONS` in
`api/leka/governance/schemas.py`. Changing one without the other fails CI —
a permission table that exists only in prose drifts from the code within a
month.

## Roles

Three, and no more.

| Role | Who it is for |
| --- | --- |
| `owner` | Whoever created the workspace, or was handed it. Answerable for the account itself. |
| `admin` | Runs the workspace day to day: members, sources, configuration. |
| `member` | Uses LEKA: reads the map, asks questions, creates intentions. |

Roles are a **chain**: an owner can do everything an admin can, an admin
everything a member can. `require_role(Role.ADMIN)` therefore admits an owner
too — listing both at every call site is how OWNER eventually gets left out
of one.

### Why not the seven roles in the mockups

The designs show Administrateur, Tech Lead, Développeur, Ops, Security,
Lecteur and Business. Those are **job titles**, and they are useful on screen.
They are not authorisation boundaries: a Tech Lead and an Ops engineer need
exactly the same things from LEKA. Modelling seven roles would mean seven
sets of permissions to keep straight, six of which are identical.

### Why no `viewer`

`member` already means "read, and create intentions". A `viewer` would differ
only by being unable to create an intention — which is most of what LEKA is
for. We have no evidence such a user exists yet.

The asymmetry decides it: adding a role later costs one `CHECK` constraint;
removing one costs migrating every existing membership. Wait for the
evidence.

## The matrix

| Permission | member | admin | owner |
| --- | --- | --- | --- |
| `workspace:read` | yes | yes | yes |
| `workspace:update` | no | yes | yes |
| `workspace:delete` | no | no | yes |
| `workspace:transfer` | no | no | yes |
| `member:read` | yes | yes | yes |
| `member:invite` | no | yes | yes |
| `member:update_role` | no | yes | yes |
| `member:remove` | no | yes | yes |
| `source:read` | yes | yes | yes |
| `source:manage` | no | yes | yes |
| `intention:read` | yes | yes | yes |
| `intention:create` | yes | yes | yes |
| `intention:approve` | no | yes | yes |
| `context:manage` | no | yes | yes |
| `job:read` | no | yes | yes |

**`job:read` is admin and above.** It reads the history of the background jobs run for the
workspace: which job, how many attempts, when. That is how the system talks to itself, and a
member has no use for it. It shows no error text — an exception message names hosts, paths and
queries — and it never shows the system's own runs, which belong to no workspace.

**`intention:approve` decides what intentions ask to do** (LEKA-390): approve, reject,
modify, ask for changes. The workspace's approval policy may want more than one person for a
risky action, and not the person who asked ([intentions.md](intentions.md) § 13); changing
that policy takes `workspace:update`. Carrying out what was approved — planning, starting,
scheduling, stopping a run, confirming a person's step — takes `intention:approve`; the
systems LEKA may act through are authorized with `workspace:update` (LEKA-391).

**`context:manage` is admin and above.** A member makes contexts, makes them again,
widens and narrows them, and archives or stops following the ones they made. Archiving
or stopping someone else's — which changes what everyone reads of it — takes an admin
([context-api.md](context-api.md)). It is a write: a suspended workspace refuses it.

**An admin cannot delete the workspace or hand it over.** Running a workspace
day to day and ending the company's account are different responsibilities,
and the person doing the first should not be one click from the second.

## Rules that hold regardless of role

**The last owner cannot be removed or demoted.** A workspace with no owner
can never be deleted, transferred or rescued — a support ticket created by
one careless click. Promote another owner first (409 otherwise).

**A suspended workspace refuses writes and allows reads.** Every permission
in `WRITE_PERMISSIONS` is refused with 403 and an explanation; everything
else works. An unpaid invoice must not look like data loss, and never a 404.

**A workspace awaiting deletion refuses writes entirely.** Access stops when
deletion is requested; the data goes at the end of the grace period.

**Removing a membership takes effect immediately.** The role is resolved from
the database on every request, never cached in the session. No sign-out, no
token refresh, no waiting.

## How a Principal is built, end to end

Since LEKA-330 the chain is complete and has no stub in it:

1. The browser sends its session cookie.
2. `leka.identity` hashes the token, finds the session row, and checks
   revocation, absolute expiry and idle timeout.
3. The seam returns the user id, and the active workspace — read from the
   session **row**, never from a header or a URL.
4. `leka.governance` reads the membership **from the database, on this
   request**, and attaches the role and the workspace's lifecycle state.
5. The route's permission dependency decides.

Step 4 is why removing a membership takes effect immediately. Caching the
role in the session is the obvious optimisation and would turn a revocation
into a delay — there is a test that fails if anyone tries it.

See [security.md](security.md) for what steps 1 to 3 protect against.

## How this is enforced

Permissions are FastAPI dependencies, never an `if` in a route body
(architecture rule 5):

```python
@router.delete("/current")
async def request_deletion(
    principal: Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_DELETE))],
    ...
```

A dependency sits in the signature where a reviewer sees it. An `if` is
forgotten in the fourteenth route by someone in a hurry, and nothing fails
until a customer reads another customer's data.

`require_permission` also runs the lifecycle check, so a suspended workspace
is refused there rather than in whichever service remembered to look.

## What is deliberately absent

Per-resource permissions, groups, custom roles and SSO-mapped roles. All are
plausible one day; none is needed by any screen that exists. See
[adr/007-tenant-isolation-strategy.md](adr/007-tenant-isolation-strategy.md).
