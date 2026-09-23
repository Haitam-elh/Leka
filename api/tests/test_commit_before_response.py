"""The transaction ends before the response is sent, on every route.

FastAPI ends a dependency with `yield` AFTER the response by default. The
database session commits in that code, so a client could receive its 200
and send its next request before the commit: signing in returned a cookie
for a session that did not exist yet, and /auth/me refused it. CI saw it as
"back on /login", one sign-in in twenty. See leka/db/session.py.
"""

from __future__ import annotations

from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from leka.db import get_session
from leka.main import app


def _session_scopes(dependant: Dependant) -> list[object]:
    found: list[object] = [dependant.scope] if dependant.call is get_session else []
    for sub in dependant.dependencies:
        found.extend(_session_scopes(sub))
    return found


def _api_routes(routes: list[Any]) -> list[APIRoute]:
    """Every APIRoute, through however many included routers."""
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        nested = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        if nested:
            found.extend(_api_routes(list(nested)))
    return found


def test_every_route_commits_before_it_answers() -> None:
    routes = _api_routes(list(app.routes))
    scopes = {route.path: _session_scopes(route.dependant) for route in routes}

    assert any(scopes.values()), "no route uses the database session — the walk is broken"
    late = sorted(path for path, found in scopes.items() if any(s != "function" for s in found))
    assert not late, f"these routes commit after answering: {late}"
