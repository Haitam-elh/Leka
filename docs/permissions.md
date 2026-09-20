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
