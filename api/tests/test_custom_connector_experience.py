"""What the custom-connector experience asks of the API (LEKA-426).

Three promises the screens rest on, against Helpdesk (the system LEKA has
no connector for, tests/test_custom_rest_connector.py):

- WHAT LEKA CANNOT DO IS SAID, not failed as something else: an answer in
  XML or CSV, a redirect to a sign-in page, a challenge for Windows or
  Digest authentication, a certificate that is not public or one asked of
  LEKA — `UNSUPPORTED`, naming what was asked.
- NO SECRET IN WHAT EVERY MEMBER READS: a user or a password in an
  address, a parameter or a variable named as a credential, are refused
  when saved.
- THE TEST SHOWS THE MAPPING AT WORK — what it read in each resource's
  first record — and that preview is returned, never stored.
"""

# ruff: noqa: F811 — the fixtures of test_custom_rest_connector are imported to be requested by name.
from __future__ import annotations

import json
import ssl
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import text

from leka.connectors import (
    ConnectionTestResult,
    DiagnosticCode,
    Source,
    SourceService,
)
from leka.connectors.custom import CustomGraphQLConfig, CustomRestConfig
from leka.db import session_factory, workspace_scope
from tests.test_custom_rest_connector import (  # noqa: F401 — fixtures
    BASE,
    DEFINITION,
    SECRET,
    Helpdesk,
    _connector,
    _failure,
    pipeline,
    source,
)


def _answering(status: int = 200, **response: Any) -> Helpdesk:
    """Helpdesk, its tickets answered as given."""
    return Helpdesk({"/tickets": lambda request: httpx.Response(status, **response)})


def _only_tickets() -> dict[str, Any]:
    return {**DEFINITION, "resources": [DEFINITION["resources"][0]]}


# ── what LEKA cannot do, said ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("content_type", "body", "said"),
    [
        ("application/xml", "<tickets/>", "XML"),
        ("text/xml; charset=utf-8", "<soap:Envelope/>", "SOAP"),
        ("application/soap+xml", "<soap:Envelope/>", "XML"),
        ("text/csv", "id,subject\n101,VPN", "text/csv"),
        ("application/octet-stream", "\x00\x01", "application/octet-stream"),
    ],
)
async def test_an_answer_in_a_format_leka_cannot_read_is_named(
    content_type: str, body: str, said: str
) -> None:
    helpdesk = _answering(content=body.encode(), headers={"content-type": content_type})

    error = await _failure(_connector(helpdesk, definition=_only_tickets()))

    assert error.diagnostic.code is DiagnosticCode.UNSUPPORTED
    assert said in error.diagnostic.message
    assert "support@leka-core.com" in error.diagnostic.remediation


async def test_a_web_page_is_an_address_to_check_not_a_format() -> None:
    helpdesk = _answering(content=b"<html>Sign in</html>", headers={"content-type": "text/html"})

    error = await _failure(_connector(helpdesk, definition=_only_tickets()))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "page web" in error.diagnostic.message
    assert "SSO, OAuth" in error.diagnostic.message


async def test_a_redirect_to_a_sign_in_page_is_oauth_or_sso_which_leka_cannot_do() -> None:
    login = "https://login.acme.example/oauth2/authorize?client_id=x&token=" + SECRET
    helpdesk = _answering(302, headers={"location": login})

    error = await _failure(_connector(helpdesk, definition=_only_tickets()))

    assert error.diagnostic.code is DiagnosticCode.UNSUPPORTED
    assert "login.acme.example" in error.diagnostic.message
    assert "OAuth, SSO" in error.diagnostic.message
    assert SECRET not in error.diagnostic.message
    assert SECRET not in (error.diagnostic.detail or "")


async def test_any_other_redirect_is_an_address_to_correct() -> None:
    helpdesk = _answering(301, headers={"location": "https://helpdesk.acme.example/api/v3/tickets"})

    error = await _failure(_connector(helpdesk, definition=_only_tickets()))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "helpdesk.acme.example/api/v3/tickets" in error.diagnostic.message
    assert "ne suit pas les redirections" in error.diagnostic.message


@pytest.mark.parametrize(
    ("challenge", "code", "said"),
    [
        ("Negotiate", DiagnosticCode.UNSUPPORTED, "Windows"),
        ("NTLM", DiagnosticCode.UNSUPPORTED, "Windows"),
        ('Digest realm="helpdesk", nonce="abc"', DiagnosticCode.UNSUPPORTED, "Digest"),
        ('Bearer error="invalid_token"', DiagnosticCode.AUTH_INVALID, "refuse ce secret"),
    ],
)
async def test_an_authentication_leka_does_not_speak_is_named(
    challenge: str, code: DiagnosticCode, said: str
) -> None:
    helpdesk = _answering(401, headers={"www-authenticate": challenge}, json={})

    error = await _failure(_connector(helpdesk, definition=_only_tickets()))

    assert error.diagnostic.code is code
    assert said in error.diagnostic.message


def _tls(failure: BaseException) -> httpx.MockTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("TLS handshake failed", request=request) from failure

    return httpx.MockTransport(refuse)


@pytest.mark.parametrize(
    ("failure", "code", "said"),
    [
        (
            ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed"),
            DiagnosticCode.UNSUPPORTED,
            "auto-signé",
        ),
        (
            ssl.SSLError(1, "[SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED] certificate required"),
            DiagnosticCode.UNSUPPORTED,
            "certificat client",
        ),
        (ConnectionRefusedError(111, "Connection refused"), DiagnosticCode.NETWORK_UNREACHABLE, ""),
    ],
)
async def test_a_certificate_leka_cannot_trust_or_present_is_named(
    failure: BaseException, code: DiagnosticCode, said: str
) -> None:
    connector = _connector(definition=_only_tickets())
    connector._transport = _tls(failure)  # the network, failing as it would

    error = await _failure(connector)

    assert error.diagnostic.code is code
    assert said in error.diagnostic.message


# ── no secret in what every member reads ─────────────────────────────────────


def _definition_with(**resource: Any) -> str:
    return json.dumps({"resources": [DEFINITION["resources"][0] | resource]})


@pytest.mark.parametrize(
    "config",
    [
        {"base_url": f"https://ops:{SECRET}@helpdesk.acme.example/api/v2"},
        {"base_url": f"https://helpdesk.acme.example/api/v2?api_key={SECRET}"},
        {"definition": _definition_with(params={"api_key": SECRET})},
        {"definition": _definition_with(params={"access_token": SECRET})},
        {"definition": _definition_with(params={"X-Auth-Token": SECRET})},
    ],
)
def test_a_secret_in_the_rest_settings_is_refused_when_saved(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as refused:
        CustomRestConfig.model_validate(
            {"base_url": BASE, "definition": json.dumps(DEFINITION)} | config
        )

    said = str(refused.value)
    assert "secret" in said or "password" in said
    assert "credentials" in said or "Secret field" in said


def test_what_only_looks_like_a_secret_is_kept() -> None:
    config = CustomRestConfig.model_validate(
        {
            "base_url": f"{BASE}?locale=fr",
            "definition": _definition_with(
                params={"pageToken": "", "status": "open", "author": "ada", "filter[key]": "x"}
            ),
        }
    )

    assert config.base_url.query == "locale=fr"


QUERY = "query Issues($first: Int!) { issues(first: $first) { nodes { id title } } }"


@pytest.mark.parametrize(
    "config",
    [
        {"endpoint": f"https://ops:{SECRET}@api.tracker.example/graphql"},
        {
            "definition": json.dumps(
                {
                    "resources": [
                        {
                            "name": "issues",
                            "query": QUERY,
                            "variables": {"token": SECRET},
                            "items": "data.issues.nodes",
                            "mapping": {"id": "id", "title": "title"},
                        }
                    ]
                }
            )
        },
    ],
)
def test_a_secret_in_the_graphql_settings_is_refused_when_saved(config: dict[str, Any]) -> None:
    definition = {
        "resources": [
            {
                "name": "issues",
                "query": QUERY,
                "items": "data.issues.nodes",
                "mapping": {"id": "id", "title": "title"},
            }
        ]
    }
    with pytest.raises(ValidationError, match=r"secret|password"):
        CustomGraphQLConfig.model_validate(
            {
                "endpoint": "https://api.tracker.example/graphql",
                "definition": json.dumps(definition),
            }
            | config
        )


# ── the test shows the mapping at work ───────────────────────────────────────


async def test_the_test_shows_what_the_mapping_read_in_each_resource() -> None:
    result = await _connector().test_connection()

    tickets, agents, assets = result.preview
    assert (tickets.name, tickets.entity, tickets.read) == ("tickets", "issue", 2)
    assert tickets.fields == {
        "id": "101",
        "title": "VPN drops every hour",
        "url": "https://helpdesk.acme.example/tickets/101",
        "state": "Open",
        "created_at": "2026-09-20T08:00:00Z",
        "updated_at": "1790000000",
        "description": "Since Monday the VPN drops.",
        "author": "ada@acme.example",
        "metadata.priority": "high",
        "metadata.tags": '["network", "vpn"]',
        "metadata.team": '{"team": "infra"}',
    }
    assert tickets.missing == []
    assert (agents.name, agents.entity, agents.fields["title"]) == ("agents", None, "Agent 1")
    assert assets.fields == {"id": "SN-1", "title": "Laptop 1"}


async def test_the_preview_says_what_the_first_record_lacks_cuts_long_values_hides_the_secret() -> (
    None
):
    first = {
        "id": 7,
        "subject": "x" * 500,
        "description": f"pasted by mistake: {SECRET}",
    }
    helpdesk = _answering(json={"data": [first], "meta": {"next_cursor": None}})

    result = await _connector(helpdesk, definition=_only_tickets()).test_connection()

    [tickets] = result.preview
    assert len(tickets.fields["title"]) == 120
    assert tickets.fields["title"].endswith("…")
    assert tickets.fields["description"] == "pasted by mistake: ••••"
    assert tickets.missing == [
        "url",
        "state",
        "created_at",
        "updated_at",
        "author",
        "metadata.priority",
        "metadata.tags",
        "metadata.team",
    ]


async def test_an_empty_first_page_is_previewed_as_empty() -> None:
    helpdesk = _answering(json={"data": [], "meta": {"next_cursor": None}})

    result = await _connector(helpdesk, definition=_only_tickets()).test_connection()

    [tickets] = result.preview
    assert (tickets.read, tickets.fields) == (0, {})
    assert "vide" in result.warnings[0]


async def test_the_preview_is_returned_never_stored(source: Source) -> None:
    """The system's own values — a title, an address — are shown to the
    admin testing, and kept nowhere: not in the source's metadata, which is
    stored, nor in its history."""
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            service = SourceService(session, source.workspace_id, actor_user_id=None)
            current = await service.get(source.id)
            result, failure = await service.test(current)
            await session.commit()
            assert failure is None and result is not None
            assert result.preview[0].fields["title"] == "VPN drops every hour"

            stored = await service.get(source.id)
            assert stored.source_metadata == {"resources": {"tickets": 2, "agents": 2, "assets": 2}}
            history = (
                await session.execute(
                    text("SELECT CAST(payload AS text) FROM source_events WHERE source_id = :s"),
                    {"s": source.id},
                )
            ).scalars()
            assert not any("VPN" in str(payload) for payload in history)


def test_every_test_result_can_carry_a_preview() -> None:
    """Every connector's result: an empty list unless it says otherwise."""
    assert ConnectionTestResult(capabilities=[]).preview == []
