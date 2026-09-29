"""The generic webhook connector: a system LEKA has no connector for, that
sends what changed (LEKA-350).

The system is Helpdesk again (tests/test_custom_rest_connector.py reads its
API) — this time sending: a ticket event per change, a batch of assets now
and then. Nothing of it is in LEKA's code: the definition below is what an
admin types, and it is the whole integration, from the signature to the
records.

What these protect: nothing is taken that is not signed with the secret —
three ways, each compared in constant time, a replay refused where the
signature carries its time; a delivery is read as the definition says, or
refused with a reason its sender can act on; what it holds is stored as a
record read from an API is, so extraction and normalisation need nothing of
their own. The door, the inbox and the pass are tests/test_webhook_deliveries.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import (
    Capability,
    ConnectorCategory,
    ConnectorError,
    ConnectorManifest,
    DiagnosticCode,
    HealthStatus,
    RefusedDeliveryError,
    SourceKind,
    get_connector,
    manifests,
    register_connector,
)
from leka.connectors.custom import CustomWebhookConfig, CustomWebhookConnector, WebhookCredentials
from leka.connectors.custom import definition as definitions
from leka.connectors.custom.rest import CustomRestConnector
from leka.ingestion.extraction import ExtractedRecord, extract
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse

SECRET = "helpdesk-hooks-7c1e9f0a2b"
NOW = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)

DEFINITION: dict[str, Any] = {
    "version": 1,
    "resources": [
        {
            "name": "tickets",
            "entity": "issue",
            "match": {
                "path": "event",
                "equals": ["ticket.created", "ticket.updated", "ticket.deleted"],
            },
            "deleted": {"path": "event", "equals": "ticket.deleted"},
            "items": "ticket",
            "mapping": {
                "id": "id",
                "title": "subject",
                "url": "html_url",
                "state": "status",
                "updated_at": "updated_at",
                "author": "requester.email",
                "metadata": {"priority": "priority"},
            },
        },
        {
            "name": "assets",
            "entity": "service",
            "match": {"path": "type", "equals": "asset.batch"},
            "items": "assets",
            "mapping": {"id": "serial", "title": "model"},
        },
    ],
}


def ticket(event: str = "ticket.updated", **overrides: Any) -> dict[str, Any]:
    return {
        "event": event,
        "ticket": {
            "id": 101,
            "subject": "VPN drops every hour",
            "html_url": "https://helpdesk.acme.example/t/101",
            "status": "Open",
            "updated_at": "2026-09-29T07:55:00Z",
            "requester": {"email": "ada@acme.example"},
            "priority": "high",
            **overrides,
        },
    }


def _body(document: object) -> bytes:
    return json.dumps(document).encode()


def _connector(
    definition: dict[str, Any] | None = None, *, secret: str = SECRET, **config: Any
) -> CustomWebhookConnector:
    return CustomWebhookConnector(
        CustomWebhookConfig(definition=json.dumps(definition or DEFINITION), **config),
        WebhookCredentials(secret=SecretStr(secret)),
    )


def _hmac(body: bytes, secret: str = SECRET) -> bytes:
    return hmac.new(secret.encode(), body, hashlib.sha256).digest()


def _refused(call: Any) -> RefusedDeliveryError:
    with pytest.raises(RefusedDeliveryError) as caught:
        call()
    return caught.value


# ── the manifest ─────────────────────────────────────────────────────────────


def test_the_webhook_is_the_one_custom_kind_that_is_sent_to() -> None:
    manifest = get_connector(SourceKind.CUSTOM_WEBHOOK).manifest

    assert (manifest.display_name, manifest.category) == (
        "Webhook entrant",
        ConnectorCategory.CUSTOM,
    )
    assert manifest.capabilities == {Capability.RECORDS}
    assert manifest.listed_whole == frozenset()  # never swept: what is not sent is not gone
    assert [m.key for m in manifests() if m.receives] == [SourceKind.CUSTOM_WEBHOOK]


def test_a_manifest_that_receives_belongs_to_a_receiver_and_only_to_one() -> None:
    class Pretends(CustomRestConnector):
        manifest = ConnectorManifest(
            **{**CustomRestConnector.manifest.model_dump(), "receives": True}
        )

    with pytest.raises(ValueError, match="Receiver"):
        register_connector(Pretends)


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("config", "found"),
    [
        ({"signature": "standard_webhooks", "signature_header": "X-Sig"}, "names its own"),
        ({"signature_header": "Content-Length"}, "not a header"),
        ({"signature_header": "X Sig"}, "not a header"),
        ({"signature": "md5"}, "signature"),
    ],
)
def test_settings_that_could_not_be_verified_are_refused_when_saved(
    config: dict[str, Any], found: str
) -> None:
    with pytest.raises(ValidationError, match=found):
        CustomWebhookConfig(definition=json.dumps(DEFINITION), **config)


def test_a_secret_is_long_enough_to_be_one() -> None:
    with pytest.raises(ValidationError):
        WebhookCredentials(secret=SecretStr("short"))


def test_a_resource_that_takes_every_delivery_comes_last_and_alone() -> None:
    catch_all = {"name": "anything", "mapping": {"id": "id", "title": "name"}}
    tickets = DEFINITION["resources"][0]

    with pytest.raises(ValueError, match="one at most, and last"):
        definitions.parse_webhook(json.dumps({"resources": [catch_all, tickets]}))
    with pytest.raises(ValueError, match="one at most, and last"):
        definitions.parse_webhook(
            json.dumps({"resources": [catch_all, {**catch_all, "name": "other"}]})
        )
    parsed = definitions.parse_webhook(json.dumps({"resources": [tickets, catch_all]}))
    assert parsed.of({"whatever": 1}) is parsed.resources[1]


def test_a_condition_compares_like_with_like() -> None:
    assert definitions.Match(path="a.b", equals=["x", "y"]).met_by({"a": {"b": "y"}})
    assert definitions.Match(path="n", equals=1).met_by({"n": 1.0})
    # true is not 1, nor "true": a condition is not a guess.
    assert not definitions.Match(path="n", equals=1).met_by({"n": True})
    assert not definitions.Match(path="n", equals=True).met_by({"n": 1})
    assert not definitions.Match(path="n", equals="true").met_by({"n": True})
    assert not definitions.Match(path="n", equals="x").met_by({"n": {"x": 1}})
    with pytest.raises(ValidationError):
        definitions.Match(path="n", equals=[])


# ── the signature ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "signature",
    [
        lambda body: "sha256=" + _hmac(body).hex(),  # GitHub's
        lambda body: _hmac(body).hex(),
        lambda body: "SHA256=" + _hmac(body).hex().upper(),
        lambda body: base64.b64encode(_hmac(body)).decode(),  # Shopify's
    ],
)
def test_a_delivery_signed_with_the_secret_is_taken(signature: Any) -> None:
    body = _body(ticket())

    _connector().verify({"x-leka-signature": signature(body)}, body, now=NOW)


def test_a_delivery_signed_otherwise_or_not_at_all_is_refused() -> None:
    body = _body(ticket())
    connector = _connector()
    signed = "sha256=" + _hmac(body).hex()

    missing = _refused(lambda: connector.verify({}, body, now=NOW))
    other_secret = _refused(
        lambda: connector.verify(
            {"x-leka-signature": "sha256=" + _hmac(body, "another-secret-entirely").hex()},
            body,
            now=NOW,
        )
    )
    altered = _refused(
        lambda: connector.verify(
            {"x-leka-signature": signed}, body.replace(b"101", b"102"), now=NOW
        )
    )

    assert [r.reason for r in (missing, other_secret, altered)] == ["signature"] * 3
    assert "X-Leka-Signature" in missing.message
    assert all(SECRET not in r.message for r in (missing, other_secret, altered))


def test_the_signature_is_read_where_the_admin_said() -> None:
    body = _body(ticket())
    connector = _connector(signature_header="X-Hub-Signature-256")
    signed = "sha256=" + _hmac(body).hex()

    connector.verify({"x-hub-signature-256": signed}, body, now=NOW)
    assert _refused(lambda: connector.verify({"x-leka-signature": signed}, body, now=NOW))


def test_a_token_is_the_secret_whole() -> None:
    connector = _connector(signature="token", signature_header="X-Gitlab-Token")
    body = _body(ticket())

    connector.verify({"x-gitlab-token": SECRET}, body, now=NOW)
    for given in (SECRET[:-1], SECRET + "x", ""):
        refused = _refused(lambda g=given: connector.verify({"x-gitlab-token": g}, body, now=NOW))
        assert refused.reason == "signature"
    # Without a header named, X-Leka-Token.
    _connector(signature="token").verify({"x-leka-token": SECRET}, body, now=NOW)


# The Standard Webhooks spec's own example (standardwebhooks.com).
SPEC_SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
SPEC_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"
SPEC_TIME = 1614265330
SPEC_BODY = b'{"test": 2432232314}'
SPEC_SIGNATURE = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def _standard(**headers: str) -> dict[str, str]:
    return {
        "webhook-id": SPEC_ID,
        "webhook-timestamp": str(SPEC_TIME),
        "webhook-signature": SPEC_SIGNATURE,
        **headers,
    }


def _spec_connector() -> CustomWebhookConnector:
    return _connector(
        {"resources": [{"name": "tests", "mapping": {"id": "test", "title": "test"}}]},
        secret=SPEC_SECRET,
        signature="standard_webhooks",
    )


def test_standard_webhooks_verifies_the_spec_s_own_example() -> None:
    at = datetime.fromtimestamp(SPEC_TIME, UTC)
    connector = _spec_connector()

    connector.verify(_standard(), SPEC_BODY, now=at)
    # While the system rotates its secret, it signs with both: one is enough.
    rotating = _standard(**{"webhook-signature": f"v1,bm90IHRoaXMgb25l {SPEC_SIGNATURE}"})
    connector.verify(rotating, SPEC_BODY, now=at)
    altered = _refused(lambda: connector.verify(_standard(), SPEC_BODY + b" ", now=at))
    assert altered.reason == "signature"
    other_id = _refused(
        lambda: connector.verify(_standard(**{"webhook-id": "msg_other"}), SPEC_BODY, now=at)
    )
    assert other_id.reason == "signature"


def test_standard_webhooks_refuses_what_was_signed_too_long_ago_or_ahead() -> None:
    signed = datetime.fromtimestamp(SPEC_TIME, UTC)
    connector = _spec_connector()

    connector.verify(_standard(), SPEC_BODY, now=signed + timedelta(seconds=299))
    for now in (signed + timedelta(seconds=301), signed - timedelta(seconds=301)):
        refused = _refused(lambda n=now: connector.verify(_standard(), SPEC_BODY, now=n))
        assert refused.reason == "stale"
    not_a_time = _standard(**{"webhook-timestamp": "yesterday"})
    assert _refused(lambda: connector.verify(not_a_time, SPEC_BODY, now=signed)).reason == "stale"


def test_standard_webhooks_needs_its_three_headers() -> None:
    at = datetime.fromtimestamp(SPEC_TIME, UTC)
    for missing in ("webhook-id", "webhook-timestamp", "webhook-signature"):
        headers = {k: v for k, v in _standard().items() if k != missing}
        refused = _refused(lambda h=headers: _spec_connector().verify(h, SPEC_BODY, now=at))
        assert refused.reason == "signature"


async def test_a_secret_that_is_not_a_standard_webhooks_one_fails_the_test() -> None:
    connector = _connector(secret="not base64 at all!!", signature="standard_webhooks")

    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    at = datetime.fromtimestamp(SPEC_TIME, UTC)
    refused = _refused(lambda: connector.verify(_standard(), SPEC_BODY, now=at))
    assert refused.reason == "signature"


# ── what a delivery holds ────────────────────────────────────────────────────


def test_a_ticket_event_is_one_record_stored_as_a_read_one_is() -> None:
    received = _connector().receive(_body(ticket()), now=NOW)

    assert (received.resource, received.gone) == ("tickets", [])
    [record] = received.records
    assert (record.kind, record.external_id, record.container) == (
        Capability.RECORDS,
        "tickets:101",
        "tickets",
    )
    assert record.payload == {
        "resource": "tickets",
        "entity": "issue",
        "fields": {
            "id": 101,
            "title": "VPN drops every hour",
            "url": "https://helpdesk.acme.example/t/101",
            "state": "Open",
            "updated_at": "2026-09-29T07:55:00Z",
            "author": "ada@acme.example",
            "metadata": {"priority": "high"},
        },
        "record": ticket()["ticket"],
    }
    assert record.updated_at == datetime(2026, 9, 29, 7, 55, tzinfo=UTC)
    assert record.fetched_at == NOW


def test_a_batch_is_as_many_records() -> None:
    batch = {
        "type": "asset.batch",
        "assets": [{"serial": "SN-1", "model": "Laptop 14"}, {"serial": 2, "model": "Dock"}],
    }

    received = _connector().receive(_body(batch), now=NOW)

    assert received.resource == "assets"
    assert [r.external_id for r in received.records] == ["assets:SN-1", "assets:2"]


def test_without_items_the_delivery_is_the_record_or_the_list_of_them() -> None:
    connector = _connector(
        {"resources": [{"name": "events", "mapping": {"id": "uid", "title": "summary"}}]}
    )

    one = connector.receive(_body({"uid": "e1", "summary": "Deploy"}), now=NOW)
    many = connector.receive(
        _body([{"uid": "e1", "summary": "A"}, {"uid": 2, "summary": "B"}]), now=NOW
    )

    assert [r.external_id for r in one.records] == ["events:e1"]
    assert [r.external_id for r in many.records] == ["events:e1", "events:2"]


def test_an_event_nobody_asked_for_is_ignored_not_refused() -> None:
    received = _connector().receive(_body({"event": "agent.logged_in", "agent": 7}), now=NOW)

    assert received.ignored
    assert (received.records, received.gone) == ([], [])


def test_a_deletion_says_which_records_are_gone_and_needs_no_title() -> None:
    deleted = {"event": "ticket.deleted", "ticket": {"id": 101}}

    received = _connector().receive(_body(deleted), now=NOW)

    assert (received.resource, received.records, received.gone) == ("tickets", [], ["tickets:101"])


@pytest.mark.parametrize(
    ("body", "reason", "said"),
    [
        (b"<xml/>", "malformed", "not JSON"),
        (b"\xff\xfe", "malformed", "not JSON"),
        (_body({"event": "ticket.updated", "ticket": "101"}), "malformed", "neither a record"),
        (_body({"event": "ticket.updated", "ticket": [1, 2]}), "malformed", "neither a record"),
        (_body(ticket(id=None)), "unmapped", "no id at « id »"),
        (_body(ticket(id={"n": 1})), "unmapped", "no id at « id »"),
        (_body(ticket(subject="  ")), "unmapped", "no title at « subject »"),
        (_body({"event": "ticket.deleted", "ticket": {"subject": "x"}}), "unmapped", "no id"),
    ],
)
def test_a_delivery_the_definition_cannot_read_is_refused_whole_with_why(
    body: bytes, reason: str, said: str
) -> None:
    refused = _refused(lambda: _connector().receive(body, now=NOW))

    assert refused.reason == reason
    assert said in refused.message


def test_one_record_the_mapping_cannot_read_refuses_the_whole_batch() -> None:
    batch = {"type": "asset.batch", "assets": [{"serial": "SN-1", "model": "L"}, {"model": "D"}]}

    refused = _refused(lambda: _connector().receive(_body(batch), now=NOW))

    assert refused.reason == "unmapped"
    assert "record 1" in refused.message  # which one, to fix it


def test_a_delivery_is_a_change_or_a_few_not_a_listing() -> None:
    batch = {
        "type": "asset.batch",
        "assets": [{"serial": n, "model": "L"} for n in range(1_001)],
    }

    refused = _refused(lambda: _connector().receive(_body(batch), now=NOW))

    assert (refused.reason, "1000" in refused.message) == ("malformed", True)


# ── the contract, where there is nothing to call ─────────────────────────────


async def test_the_test_calls_nothing_and_says_what_will_be_recognised() -> None:
    connector = _connector()

    result = await connector.test_connection()
    health = await connector.check_health()
    scope = await connector.list_scope()

    assert result.capabilities == [Capability.RECORDS]
    assert result.metadata == {"resources": ["tickets", "assets"], "signature": "hmac_sha256"}
    assert health.status is HealthStatus.HEALTHY
    assert [(o.key, o.description) for o in scope.options] == [
        ("tickets", 'event = "ticket.created" | "ticket.updated" | "ticket.deleted"'),
        ("assets", 'type = "asset.batch"'),
    ]
    with pytest.raises(NotImplementedError):
        # Nothing to read: the pass stores what was received (leka/ingestion/sync.py).
        await anext(connector.iter_resources(Capability.RECORDS))


# ── extraction and normalisation: nothing of their own ───────────────────────


def test_a_received_ticket_becomes_an_issue_as_a_read_one_does() -> None:
    [record] = _connector().receive(_body(ticket()), now=NOW).records
    source_id = uuid.UUID("11111111-2222-3333-4444-555555555555")

    extracted = extract(record, source_id=source_id, source_kind=SourceKind.CUSTOM_WEBHOOK)
    assert isinstance(extracted, ExtractedRecord)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed)

    assert isinstance(result, NormalisedRecord)
    assert result.entity.type == "issue"
    assert result.entity.key == f"custom-{source_id}:issue:tickets:101"
    assert result.entity.attributes["state_raw"] == "open"
    assert [(r.type, r.to_key) for r in result.relationships] == [
        ("authored_by", "person:email:ada@acme.example")
    ]
