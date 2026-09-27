"""Setting and clearing the two cookies authentication uses.

One place, so that a flag cannot be right on the login route and wrong on
the one someone adds next month. A cookie misconfiguration does not fail
loudly: it works perfectly everywhere and quietly stops protecting anyone.
"""

from __future__ import annotations

import secrets

from fastapi import Response

from leka.core.config import settings

CSRF_COOKIE_NAME = "leka_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def _common(max_age: int | None) -> dict[str, object]:
    return {
        # Path=/ and no Domain: a host-only cookie. Setting a Domain would
        # share it with every subdomain, including any one we do not control.
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
        # None: no Max-Age, a cookie the browser drops when it closes.
        "max_age": max_age,
    }


def set_session_cookie(response: Response, token: str, *, persistent: bool = True) -> str:
    """Attach a fresh session, and the CSRF token that goes with it.

    `persistent`: the person asked this device to remember them. Otherwise
    both cookies end with the browser.

    Returns the CSRF token so the route hands it back in the body: the page
    is served from another host than the API, and cannot read the cookie.
    """
    max_age = settings.session_absolute_lifetime_days * 24 * 3600 if persistent else None
    response.set_cookie(
        settings.session_cookie_name,
        token,
        # httpOnly: JavaScript cannot read it, so an XSS that runs in the page
        # still cannot exfiltrate the session.
        httponly=True,
        **_common(max_age),  # type: ignore[arg-type]
    )
    return set_csrf_cookie(response, max_age=max_age)


def set_csrf_cookie(response: Response, *, max_age: int | None) -> str:
    """A new CSRF token, as a cookie, returned for the body as well."""
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        # Deliberately readable: the double-submit pattern needs the page to
        # copy this value into a header. It is not a secret — its value is
        # that an attacker's site cannot read it from another origin.
        httponly=False,
        **_common(max_age),  # type: ignore[arg-type]
    )
    return csrf_token


def clear_session_cookie(response: Response) -> None:
    """Remove both cookies.

    Same path and attributes as when they were set — a delete with different
    attributes silently does nothing, and the browser keeps sending the old
    cookie.
    """
    for name in (settings.session_cookie_name, CSRF_COOKIE_NAME):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.session_cookie_secure,
            samesite=settings.session_cookie_samesite,
        )
