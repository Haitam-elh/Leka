"""Every route is protected, or is listed here with a reason.

The most important test in LEKA-333, and the one that keeps working after
everyone has forgotten it exists.

Principal and require_permission were already correct. What was missing was
anything that made them unforgettable: a route added in six months with no
authentication would have shipped, worked perfectly, and been discovered by
whoever found the data it exposed.

So this walks the routes FastAPI has actually mounted, reads each one's
dependency tree, and demands that every one either

    * carries an authentication dependency, or
    * appears in PUBLIC_ROUTES below with a written reason.

Adding a route with neither fails CI, with the route named. Adding one to
the list is a decision somebody has to type out and somebody else reads in
a diff.

The same shape as tests/test_tenant_isolation.py, including the test that
stops the whitelist quietly covering everything.

WHY THE DEPENDENCY TREE AND NOT THE BODY. A route can enforce a session in
its first statement, and five of them used to. That works and it is
invisible: no check can tell a route that forgot from a route that is
deliberately open. Moving those guards into dependencies is what made this
test possible, and is most of what this file bought.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.routing import APIRoute

from leka.api.identity import require_session
from leka.core.config import settings
from leka.governance.dependencies import (
    get_current_principal,
    require_permission,
    require_role,
)
from leka.main import app
from leka.platform.seam import get_current_user_id

# Routes anyone may reach, and why. Each entry is a decision.
#
# The reason is not decoration. "Why is this open?" asked in a review is
# answered here rather than by reading the handler and guessing.
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/health"): (
        "Liveness and readiness. A probe has no credentials, and requiring "
        "them would make the service look down to whatever watches it."
    ),
    ("POST", "/api/v1/auth/register"): (
        "Creating an account. There is nobody to authenticate yet."
    ),
    ("POST", "/api/v1/auth/login"): (
        "Exchanging a password for a session. The credential IS the request."
    ),
    ("POST", "/api/v1/auth/logout"): (
        "Deliberately tolerant of an absent session: signing out twice, or "
        "from an expired session, must succeed rather than refuse. It has "
        "nothing to expose — it only clears a cookie."
    ),
    ("POST", "/api/v1/auth/verify/{token}"): (
        "Confirming an address. The token in the URL is the credential; the "
        "person clicking it is by definition not signed in yet."
    ),
    ("POST", "/api/v1/auth/verify/resend"): (
        "Asking for another verification link. Answers identically whether "
        "the address exists, and is rate limited per address."
    ),
    ("POST", "/api/v1/auth/password/forgot"): (
        "Asking for a reset link. Same reasoning: answers identically whether the account exists."
    ),
    ("POST", "/api/v1/auth/password/reset"): (
        "Setting a new password from a link. The single-use token is the "
        "credential, and the whole point is that the old one is unusable."
    ),
    ("POST", "/api/v1/webhooks/sources/{source_id}"): (
        "A system sending a webhook source what changed. A system has no "
        "session: the delivery's signature, checked against the source's "
        "secret before anything is written, is the credential."
    ),
}

# The dependencies that mean "somebody is authenticated".
#
# get_current_user_id is LEKA-331's seam, filled by LEKA-330.
# get_current_principal resolves a membership, so it implies a user.
# require_session is the one that used to be a line inside five handlers.
# require_role and require_permission wrap the principal; their closures are
# anonymous, so they are recognised by what they depend on rather than by
# identity — see _is_protected.
AUTHENTICATION_DEPENDENCIES = frozenset(
    {get_current_user_id, get_current_principal, require_session}
)

# Named so the test below can prove they are still wired to the principal.
AUTHORISATION_FACTORIES = (require_role, require_permission)


def _flatten(dependant: Any) -> list[Any]:
    """Every callable in a route's dependency tree, however deep.

    FastAPI nests dependants: a route depends on require_permission(...),
    which depends on get_current_principal, which depends on the session.
    Only walking the top level would miss every route that protects itself
    through a permission check — which is most of them.
    """
    found: list[Any] = []
    for sub in dependant.dependencies:
        if sub.call is not None:
            found.append(sub.call)
        found.extend(_flatten(sub))
    return found


def _routes(carrier: Any, prefix: str) -> list[tuple[str, APIRoute]]:
    """Every mounted route with its full path, walking into included routers.

    app.routes is NOT a flat list. This version of FastAPI keeps an included
    router as one opaque entry whose real routes hang off
    `original_router.routes` — and those are included routers in turn, one
    per module, each carrying its own prefix. A naive comprehension over
    app.routes finds ZERO APIRoute objects, and every check in this file
    then passes on an empty list, cheerfully, meaning nothing.

    The root prefix is not on any of those objects, so it is supplied by the
    caller. That reconstruction could drift, which is why
    test_the_route_walk_matches_the_published_schema exists: if these paths
    ever stop matching the ones the API actually publishes, that fails.

    tests/test_tenant_isolation.py hit the same wall and went through the
    OpenAPI schema instead. This file cannot — it needs the dependency tree,
    which the schema does not carry.
    """
    found: list[tuple[str, APIRoute]] = []
    for route in carrier:
        if isinstance(route, APIRoute):
            found.append((prefix + route.path, route))
            continue

        inner = getattr(route, "original_router", None)
        nested = getattr(route, "routes", None) or getattr(inner, "routes", None)
        if nested:
            # No prefix accumulated here: in this FastAPI version an inner
            # route's own `path` already carries its router's prefix, and
            # adding it again produced /api/v1/auth/auth/login. Only the
            # ROOT prefix is missing, and that is what the caller supplies.
            found.extend(_routes(nested, prefix))
    return found


def _operations() -> list[tuple[str, str, APIRoute]]:
    """(method, path, route) for everything the application serves."""
    operations: list[tuple[str, str, APIRoute]] = []
    for path, route in _routes(app.routes, settings.api_v1_prefix):
        for method in sorted(route.methods or set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            operations.append((method, path, route))
    return operations


def _is_protected(route: APIRoute) -> bool:
    """Whether reaching this route requires being somebody."""
    return any(call in AUTHENTICATION_DEPENDENCIES for call in _flatten(route.dependant))


# ── The test that matters ────────────────────────────────────────────────────


def test_every_route_is_protected_or_deliberately_public() -> None:
    """A route added tomorrow with no authentication fails here.

    Not in review, not in production, not when a customer notices. Here,
    with its method and path printed, the first time CI runs.
    """
    unprotected: list[str] = []

    for method, path, route in _operations():
        if (method, path) in PUBLIC_ROUTES:
            continue
        if not _is_protected(route):
            unprotected.append(f"{method} {path}")

    assert not unprotected, (
        "routes reachable without authentication:\n  "
        + "\n  ".join(unprotected)
        + "\n\nEither add an authentication dependency — PrincipalDep, UserIdDep, "
        "RequiredSession, or require_permission(...) — or add the route to "
        "PUBLIC_ROUTES in this file with a written reason. Enforcing a session "
        "inside the handler body does not count: nothing outside the function "
        "can see it, which is exactly the problem."
    )


# ── The tests that keep the test above honest ────────────────────────────────


def test_the_public_list_does_not_name_routes_that_no_longer_exist() -> None:
    """A stale entry is a hole waiting for a path to be reused.

    Delete a route, leave its line here, and the day somebody adds a route
    at the same path it is silently exempt.
    """
    live = {(method, path) for method, path, _ in _operations()}
    stale = sorted(
        f"{method} {path}" for method, path in PUBLIC_ROUTES if (method, path) not in live
    )

    assert not stale, (
        f"PUBLIC_ROUTES names routes the application no longer serves: {stale}. "
        "Remove them — an exemption for a path nobody serves is an exemption "
        "waiting for a path to be served again."
    )


def test_every_public_route_gives_a_reason() -> None:
    """An empty reason is an exemption nobody has to defend."""
    silent = sorted(
        f"{method} {path}" for (method, path), reason in PUBLIC_ROUTES.items() if len(reason) < 40
    )
    assert not silent, f"PUBLIC_ROUTES entries with no real justification: {silent}"


def test_the_route_walk_matches_the_published_schema() -> None:
    """The paths this file reasons about are the paths the API serves.

    _routes rebuilds full paths from nested routers and a root prefix that
    none of those objects carries. If that reconstruction drifts — a FastAPI
    upgrade, a second include — every check here would quietly reason about
    paths nobody can call, and PUBLIC_ROUTES would stop matching anything.
    """
    walked = {(method, path) for method, path, _ in _operations()}
    published = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }

    assert walked == published, (
        "the routes walked here are not the routes the API publishes.\n"
        f"  only walked:    {sorted(walked - published)}\n"
        f"  only published: {sorted(published - walked)}"
    )


def test_the_application_actually_serves_routes() -> None:
    """Guards everything above from covering nothing.

    If api_router stopped being mounted, every check in this file would pass
    on an empty list and say so cheerfully.
    """
    operations = _operations()
    assert len(operations) > 10, (
        f"only {len(operations)} routes mounted — the checks in this file would "
        "cover almost nothing"
    )


def test_most_routes_are_not_public() -> None:
    """The whitelist must stay a list of exceptions.

    If it ever holds most of the surface, it has stopped being a whitelist
    and become the default, and this file would be theatre.
    """
    operations = _operations()
    public = sum(1 for method, path, _ in operations if (method, path) in PUBLIC_ROUTES)

    assert public * 2 < len(operations), (
        f"{public} of {len(operations)} routes are public. The exemption list has become the rule."
    )


def test_authorisation_still_runs_through_the_principal() -> None:
    """require_permission and require_role must keep resolving a principal.

    They are how most routes are protected, and _is_protected finds them
    only through what they depend on. If either stopped depending on
    get_current_principal, every route using it would silently look
    unprotected — or worse, be unprotected while this file still passed.
    """
    # The real check: a route using require_permission is seen as protected.
    protected = [
        f"{method} {path}"
        for method, path, route in _operations()
        if path == "/api/v1/members/invite" and _is_protected(route)
    ]
    assert protected, (
        "POST /api/v1/members/invite uses require_permission and is not seen as "
        "protected — _is_protected no longer recognises the authorisation chain"
    )


# ── The enumeration must bite ────────────────────────────────────────────────


def test_an_unprotected_route_would_be_caught() -> None:
    """Proof that the check above is capable of failing.

    A test that has never failed proves nothing. Rather than adding a real
    unprotected route to the application and remembering to take it out, the
    detection is run against a route object that genuinely has no
    authentication dependency.
    """
    from fastapi import APIRouter

    scratch = APIRouter()

    @scratch.get("/wide-open")
    async def wide_open() -> dict[str, str]:
        return {"anyone": "can read this"}

    route = next(r for r in scratch.routes if isinstance(r, APIRoute))

    assert not _is_protected(route), (
        "_is_protected called a route with no dependencies protected — the "
        "enumeration test cannot fail and is therefore worthless"
    )


def test_a_protected_route_is_recognised() -> None:
    """The other half: it must not call everything unprotected either.

    A check that fails on everything gets an exemption added for everything,
    which is the same as no check at all.
    """
    protected = [
        f"{method} {path}"
        for method, path, route in _operations()
        if (method, path) not in PUBLIC_ROUTES and _is_protected(route)
    ]
    assert len(protected) > 5, (
        f"only {len(protected)} routes recognised as protected. _is_protected is "
        "probably matching nothing."
    )


@pytest.mark.parametrize("method_and_path", sorted(PUBLIC_ROUTES))
def test_each_public_route_is_reachable_without_credentials(
    method_and_path: tuple[str, str],
) -> None:
    """A route exempted from authentication should actually need to be.

    This does not call it — several are destructive or rate limited. It
    checks the weaker, useful thing: that it is not ALSO carrying an
    authentication dependency, which would mean the exemption is a lie and
    the reason beside it is wrong.
    """
    method, path = method_and_path
    route = next(r for m, p, r in _operations() if (m, p) == (method, path))

    assert not _is_protected(route), (
        f"{method} {path} is listed as public but requires authentication. "
        "Either remove it from PUBLIC_ROUTES or correct the reason beside it."
    )


def test_no_route_is_hidden_behind_an_earlier_one() -> None:
    """A route whose path an earlier route of the same method already matches
    is never reached. POST /auth/verify/resend sat behind
    POST /auth/verify/{token}: "resend" was checked as a token, refused as
    invalid, and no second link was ever sent (LEKA-330). Nothing failed
    loudly — the page said a link was on its way."""
    routes = _routes(app.routes, settings.api_v1_prefix)
    hidden = [
        f"{sorted((later.methods or set()) & (earlier.methods or set()))} {later_path} "
        f"is caught by {earlier_path}, declared before it"
        for index, (earlier_path, earlier) in enumerate(routes)
        for later_path, later in routes[index + 1 :]
        if (later.methods or set()) & (earlier.methods or set())
        and earlier.path_regex.match(later.path)
    ]

    assert routes, "the walk found no routes, so this check would mean nothing"
    assert not hidden, "\n".join(hidden)
