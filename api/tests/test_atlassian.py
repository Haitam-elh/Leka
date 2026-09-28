"""What Jira and Confluence share (leka/connectors/atlassian.py), on its own.

The site is the part an admin types, so it is the part that could send
LEKA's requests somewhere else. Every way of writing a real site gives its
name; everything else is refused before a request exists.
"""

from __future__ import annotations

import base64

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import DiagnosticCode, HealthStatus
from leka.connectors.atlassian import (
    AtlassianCredentials,
    headers,
    health,
    refuser,
    site_name,
    site_url,
)

TOKEN = "ATATT3xFfGF0Abcdefghij0123456789_secretpart"
EMAIL = "nora@acme.test"
CREDENTIALS = AtlassianCredentials(token=SecretStr(TOKEN), email=EMAIL)


@pytest.mark.parametrize(
    "typed",
    [
        "acme",
        "ACME",
        " acme ",
        "acme.atlassian.net",
        "https://acme.atlassian.net",
        "https://acme.atlassian.net/jira/software/projects/PAY/boards/1",
        "http://acme.atlassian.net/wiki/home",
    ],
)
def test_every_way_of_writing_a_site_gives_its_name(typed: str) -> None:
    assert site_name(typed) == "acme"
    assert site_url(site_name(typed)) == "https://acme.atlassian.net"


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "evil.example",
        "https://evil.example/acme",
        "acme.atlassian.net.evil.example",
        "acme.atlassian.net@evil.example",
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "[::1]",
        "acme:8080",
        "-acme",
        "acme-",
        "ac me",
        "a" * 64,
    ],
)
def test_nothing_but_a_site_under_atlassian_net_is_accepted(typed: str) -> None:
    """The host is built, never typed: no address inside LEKA's network,
    no other domain, no port, can come out of this."""
    with pytest.raises(ValueError, match="site"):
        site_name(typed)


def test_a_name_that_looks_local_is_still_a_host_under_atlassian_net() -> None:
    """A name is only ever the first label: "localhost" is a site called
    localhost, at Atlassian, not this machine."""
    assert site_url(site_name("localhost")) == "https://localhost.atlassian.net"
    assert httpx.URL(site_url(site_name("localhost"))).host == "localhost.atlassian.net"


def test_the_account_signs_in_with_its_email_and_token() -> None:
    sent = headers(CREDENTIALS)["Authorization"]

    assert sent == "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()


def test_the_token_is_first_so_the_stored_hint_is_the_token_s() -> None:
    assert next(iter(AtlassianCredentials.model_fields)) == "token"
    assert TOKEN not in repr(CREDENTIALS)


@pytest.mark.parametrize("email", ["nora", "nora@", "no ra@acme.test", ""])
def test_an_email_that_is_not_one_is_refused(email: str) -> None:
    with pytest.raises(ValidationError):
        AtlassianCredentials(token=SecretStr(TOKEN), email=email)


def _refusal(response: httpx.Response, missing: str = "") -> tuple[DiagnosticCode, str]:
    response.request = httpx.Request("GET", "https://acme.atlassian.net/rest/api/3/myself")
    error = refuser("Jira", CREDENTIALS)(response, "/myself", missing)
    assert TOKEN not in repr(error.diagnostic)
    return error.diagnostic.code, error.diagnostic.message


def test_a_redirect_is_a_site_that_does_not_exist() -> None:
    moved = httpx.Response(302, headers={"location": "https://www.atlassian.com/"})

    code, message = _refusal(moved)

    assert code is DiagnosticCode.NOT_FOUND
    assert "n'existe pas" in message


def test_a_refused_sign_in_names_both_halves() -> None:
    code, message = _refusal(httpx.Response(401, text="Unauthorized"))

    assert code is DiagnosticCode.AUTH_INVALID
    assert "adresse e-mail ou ce token" in message


def test_a_token_short_of_a_scope_says_so() -> None:
    body = {"code": 403, "message": "scope does not match"}

    assert _refusal(httpx.Response(403, json=body))[0] is DiagnosticCode.INSUFFICIENT_SCOPE
    assert _refusal(httpx.Response(403, json={}))[0] is DiagnosticCode.PERMISSION_DENIED


def test_what_is_missing_is_named() -> None:
    code, message = _refusal(httpx.Response(404, json={}), missing="ce projet")

    assert code is DiagnosticCode.NOT_FOUND
    assert message == "Jira ne trouve pas ce projet, ou ce compte ne le voit pas."


def test_an_exhausted_quota_says_when_to_come_back() -> None:
    response = httpx.Response(429, headers={"retry-after": "30"})
    response.request = httpx.Request("GET", "https://acme.atlassian.net/rest/api/3/myself")

    error = refuser("Jira", CREDENTIALS)(response, "/myself", "")

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retry_after == 30


def test_an_echoed_token_is_removed_from_the_detail() -> None:
    response = httpx.Response(500, text=f"boom, your token was {TOKEN}")
    response.request = httpx.Request("GET", "https://acme.atlassian.net/rest/api/3/myself")

    error = refuser("Jira", CREDENTIALS)(response, "/myself", "")

    assert error.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert TOKEN not in (error.diagnostic.detail or "")


def test_health_is_degraded_when_the_quota_is_nearly_spent() -> None:
    near = health(httpx.Response(200, headers={"x-ratelimit-nearlimit": "true"}))
    fine = health(httpx.Response(200))

    assert (near.status, near.detail) == (HealthStatus.DEGRADED, "quota presque épuisé")
    assert (fine.status, fine.detail) == (HealthStatus.HEALTHY, None)
