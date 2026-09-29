"""The generic webhook — a system LEKA has no connector for, that SENDS what
changed (LEKA-350).

The REST and GraphQL connectors read; this one is sent to. The system posts
each change to the source's own address,

    POST /api/v1/webhooks/sources/<source id>

signed with a secret the admin gave both sides. The definition says what a
delivery may be: for each resource, the condition that recognises it
(`match`), where its records are (`items`), what their fields mean
(`mapping`), and the condition that says they were deleted (`deleted`). So
the records received are the records a REST source reads — stored,
extracted and normalised the same way (leka/connectors/receiving.py).

SIGNED, three ways — the ones systems use:

    hmac_sha256        the HMAC-SHA256 of the body, keyed with the secret, in
                       a header (X-Leka-Signature by default): hex, after
                       `sha256=` or not — GitHub's way — or base64 — Shopify's
    standard_webhooks  the Standard Webhooks spec (standardwebhooks.com):
                       webhook-id, webhook-timestamp, webhook-signature, a
                       `whsec_…` secret. Signed with its time: a delivery
                       signed more than five minutes from now is refused — a
                       replay, or a clock to set
    token              the secret itself, in a header (X-Leka-Token by
                       default) — GitLab's way, and many in-house tools'

Compared in constant time. The secret is in no answer, and no log.

NOTHING TO CALL. The test checks the secret's form and says what the
definition recognises; the health is always good — a system that stops
sending is not something LEKA can tell from silence. The log of deliveries
(GET /ingestion/sources/{id}/deliveries) says when the last one came.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.custom.common import (
    HEADER,
    TRANSPORT_HEADERS,
    external_of,
    readable,
    record_of,
)
from leka.connectors.custom.definition import (
    DEFINITION_MAX,
    Match,
    WebhookResource,
    at,
    fields,
    identifier,
    parse_webhook,
)
from leka.connectors.errors import DiagnosticCode, diagnose
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.receiving import Received, Receiver, RefusedDeliveryError
from leka.connectors.registry import register_connector

C = Capability

Signature = Literal["hmac_sha256", "standard_webhooks", "token"]
DEFAULT_HEADER: dict[Signature, str] = {
    "hmac_sha256": "X-Leka-Signature",
    "token": "X-Leka-Token",
}
# Standard Webhooks' own tolerance: how far from now a signature's time may be.
TOLERANCE_SECONDS = 300
# A delivery is a change or a few: more is a listing, which a REST source reads.
MAX_DELIVERY_RECORDS = 1_000
SECRET_MIN = 16
WHSEC = "whsec_"


class CustomWebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature: Signature = Field(
        default="hmac_sha256",
        description="How the system signs what it sends: hmac_sha256 (an HMAC of the body), "
        "standard_webhooks (the Standard Webhooks spec), token (the secret itself, in a header).",
    )
    signature_header: str | None = Field(
        default=None,
        max_length=64,
        description="For hmac_sha256 and token: the header that carries it — X-Leka-Signature "
        "or X-Leka-Token when empty.",
    )
    definition: str = Field(
        min_length=2,
        max_length=DEFINITION_MAX,
        description="What a delivery may be — conditions, records, mapping — as JSON.",
        json_schema_extra={"format": "json"},
    )

    @field_validator("definition")
    @classmethod
    def _readable(cls, value: str) -> str:
        parse_webhook(value)
        return value

    @model_validator(mode="after")
    def _a_header_where_one_is_read(self) -> Self:
        name = self.signature_header
        if name is None:
            return self
        if self.signature == "standard_webhooks":
            msg = "standard_webhooks names its own headers: signature_header stays empty"
            raise ValueError(msg)
        if not re.fullmatch(HEADER, name) or name.lower() in TRANSPORT_HEADERS:
            msg = f"{name!r} is not a header a signature can be read from"
            raise ValueError(msg)
        return self

    @property
    def header(self) -> str:
        """The header the signature, or the token, is read from."""
        return self.signature_header or DEFAULT_HEADER.get(self.signature, "webhook-signature")


class WebhookCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr = Field(
        min_length=SECRET_MIN,
        max_length=4096,
        description="The secret both sides share, 16 characters at least — for "
        "standard_webhooks, the whsec_… the system gives.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


@register_connector
class CustomWebhookConnector(Connector[CustomWebhookConfig, WebhookCredentials], Receiver):
    manifest = ConnectorManifest(
        key=SourceKind.CUSTOM_WEBHOOK,
        display_name="Webhook entrant",
        category=ConnectorCategory.CUSTOM,
        auth_type="token",
        config_schema=CustomWebhookConfig,
        credentials_schema=WebhookCredentials,
        capabilities=frozenset({C.RECORDS}),
        receives=True,
    )

    def __init__(
        self,
        config: CustomWebhookConfig,
        credentials: WebhookCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config, credentials, transport=transport)
        self.definition = parse_webhook(config.definition)

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        """Nothing to reach: the secret's form, and what will be recognised."""
        if self.config.signature == "standard_webhooks" and self._key() is None:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Ce secret n'est pas un secret Standard Webhooks : copiez le whsec_… "
                "que le système donne.",
            )
        return ConnectionTestResult(
            account=None,
            metadata={
                "resources": [resource.name for resource in self.definition.resources],
                "signature": self.config.signature,
            },
            capabilities=[C.RECORDS],
        )

    async def check_health(self) -> HealthResult:
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        """The resources: a record's container is its resource."""
        return ScopeListing(
            options=[
                ScopeOption(key=r.name, name=r.name, description=_described(r.match))
                for r in self.definition.resources
            ]
        )

    # ── receiving ────────────────────────────────────────────────────────────

    def verify(self, headers: Mapping[str, str], body: bytes, *, now: datetime) -> None:
        if self.config.signature == "standard_webhooks":
            self._standard(headers, body, now)
            return
        header = self.config.header
        given = headers.get(header.lower(), "").strip()
        if not given:
            raise RefusedDeliveryError(
                "signature", f"No {header} header: the delivery is not signed."
            )
        secret = self.credentials.secret.get_secret_value().encode()
        if self.config.signature == "token":
            if not hmac.compare_digest(given.encode(), secret):
                raise RefusedDeliveryError("signature", f"{header} is not the source's token.")
            return
        digest = hmac.new(secret, body, hashlib.sha256).digest()
        value = given[7:] if given[:7].lower() == "sha256=" else given
        # Both compared, whichever it is: the time taken says nothing.
        as_hex = hmac.compare_digest(value.lower().encode(), digest.hex().encode())
        as_base64 = hmac.compare_digest(value.encode(), base64.b64encode(digest))
        if not (as_hex or as_base64):
            raise RefusedDeliveryError(
                "signature",
                f"{header} does not match the body: check the secret, and that the body is "
                "signed as it is sent.",
            )

    def receive(self, body: bytes, *, now: datetime) -> Received:
        try:
            delivery = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise RefusedDeliveryError("malformed", "The body is not JSON.") from None
        resource = self.definition.of(delivery)
        if resource is None:
            return Received(resource=None)
        items = _records_in(resource, delivery)
        deleted = resource.deleted is not None and resource.deleted.met_by(delivery)
        records = []
        gone = []
        for position, item in enumerate(items):
            found = fields(resource.mapping, item)
            external_id = identifier(found.get("id"))
            if external_id is None:
                raise _unmapped(resource, position, "id", resource.mapping.id)
            if deleted:
                gone.append(external_of(resource, external_id))
                continue
            if not readable(found.get("title")):
                raise _unmapped(resource, position, "title", resource.mapping.title)
            records.append(record_of(resource, external_id, found, item, now))
        return Received(resource=resource.name, records=records, gone=gone)

    # ── the signature ────────────────────────────────────────────────────────

    def _standard(self, headers: Mapping[str, str], body: bytes, now: datetime) -> None:
        """Standard Webhooks: `{id}.{timestamp}.{body}`, HMAC-SHA256 keyed
        with the secret's bytes, base64 — one `v1,<signature>` of those the
        header lists, space apart, while the system rotates its secret."""
        delivery_id = headers.get("webhook-id", "")
        sent = headers.get("webhook-timestamp", "")
        signatures = headers.get("webhook-signature", "")
        if not (delivery_id and sent and signatures):
            raise RefusedDeliveryError(
                "signature",
                "A Standard Webhooks delivery carries webhook-id, webhook-timestamp and "
                "webhook-signature.",
            )
        if not sent.isdigit():
            raise RefusedDeliveryError("stale", "webhook-timestamp is not a time in seconds.")
        if abs(now.timestamp() - int(sent)) > TOLERANCE_SECONDS:
            raise RefusedDeliveryError(
                "stale",
                "Signed more than five minutes from now: a delivery replayed, or a clock to set.",
            )
        key = self._key()
        if key is None:
            raise RefusedDeliveryError(
                "signature", "The source's secret is not a Standard Webhooks secret."
            )
        signed = f"{delivery_id}.{sent}.".encode() + body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest())
        found = False
        for entry in signatures.split():
            version, _, value = entry.partition(",")
            found |= version == "v1" and hmac.compare_digest(value.encode(), expected)
        if not found:
            raise RefusedDeliveryError(
                "signature", "webhook-signature does not match: check the secret."
            )

    def _key(self) -> bytes | None:
        """A Standard Webhooks secret's key: base64 after `whsec_`."""
        secret = self.credentials.secret.get_secret_value()
        encoded = secret.removeprefix(WHSEC)
        try:
            return base64.b64decode(encoded, validate=True) or None
        except (binascii.Error, ValueError):
            return None


def _records_in(resource: WebhookResource, delivery: object) -> list[dict[str, Any]]:
    """Where `items` says, or the delivery itself: one record, or a list."""
    found = at(delivery, resource.items) if resource.items else delivery
    if isinstance(found, dict):
        return [found]
    if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
        where = f"« {resource.items} »" if resource.items else "the delivery"
        raise RefusedDeliveryError(
            "malformed",
            f"« {resource.name} »: {where} is neither a record nor a list of records.",
        )
    if len(found) > MAX_DELIVERY_RECORDS:
        raise RefusedDeliveryError(
            "malformed", f"More than {MAX_DELIVERY_RECORDS} records in one delivery."
        )
    return found


def _unmapped(
    resource: WebhookResource, position: int, name: str, path: str
) -> RefusedDeliveryError:
    return RefusedDeliveryError(
        "unmapped",
        f"« {resource.name} », record {position}: no {name} at « {path} ». "
        "Nothing of the delivery is kept: check the mapping, or what is sent.",
    )


def _described(match: Match | None) -> str:
    if match is None:
        return "toute livraison"
    wanted = match.equals if isinstance(match.equals, list) else [match.equals]
    return f"{match.path} = {' | '.join(json.dumps(value) for value in wanted)}"
