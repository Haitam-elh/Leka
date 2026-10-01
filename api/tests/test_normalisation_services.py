"""Applications and services, normalised (LEKA-362).

Vendor payloads through extraction and parsing, then normalisation, as in
tests/test_normalisation.py. What matters: every tool that names a service
or an application names it by one key; what a catalogue says — the owner,
the application, what a service depends on, how critical it is, where it is
in its life — becomes relationships and attributes on LEKA's scales, the
tool's word kept beside; an environment is an entity things run in; and a
tag, a catalogue or a custom source's admin say the same things the same
way.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, Mapping, SourceKind
from leka.connectors.settings import TagKeys
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse
from tests.test_datadog_resources import BILLING_V22, LEDGER_V3
from tests.test_extraction import _extract
from tests.test_pagerduty_connector import CHECKOUT as PAGERDUTY_CHECKOUT
from tests.test_pagerduty_connector import ONLINE_SHOP

C = Capability
ARN = "arn:aws:ec2:eu-west-3:123456789012"


def _normalised(
    kind: SourceKind,
    capability: Capability,
    payload: dict[str, Any],
    mapping: Mapping | None = None,
    **extra: Any,
) -> NormalisedRecord:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed, mapping)
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str, str]]:
    return {(r.from_key, r.type, r.to_key) for r in record.relationships}


def _related(record: NormalisedRecord) -> dict[str, str]:
    return {e.key: e.type for e in record.related}


def _instance(tags: dict[str, str], mapping: Mapping | None = None) -> NormalisedRecord:
    return _normalised(
        SourceKind.AWS,
        C.INSTANCES,
        {"InstanceId": "i-1", "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]},
        mapping,
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-1",
    )


# ── cloud tags ───────────────────────────────────────────────────────────────


def test_an_application_tag_beside_a_service_tag_says_the_service_s_application() -> None:
    instance = _instance({"service": "billing-api", "application": "Billing", "env": "prod"})

    key = instance.entity.key
    assert _related(instance) == {
        "service:billing-api": "service",
        "application:billing": "application",
        "environment:production": "environment",
        # What it is in (LEKA-363).
        "aws:account:123456789012": "cloud_account",
    }
    assert {
        (key, "part_of", "service:billing-api"),
        ("service:billing-api", "part_of", "application:billing"),
        (key, "runs_in", "environment:production"),
    } <= _edges(instance)
    assert (key, "part_of", "application:billing") not in _edges(instance)


def test_an_application_tag_alone_says_the_resource_s_application() -> None:
    instance = _instance({"system": "Billing"})

    assert (instance.entity.key, "part_of", "application:billing") in _edges(instance)


def test_how_critical_a_resource_is_is_on_leka_s_scale() -> None:
    tiered = _instance({"tier": "1"})
    worded = _instance({"criticality": "Mission-Critical"})

    assert tiered.entity.attributes["criticality"] == "critical"
    assert worded.entity.attributes["criticality"] == "critical"
    assert worded.entity.attributes["criticality_confidence"] == 0.95


def test_only_a_canonical_environment_is_an_entity() -> None:
    sandbox = _instance({"env": "sandbox-7"})

    assert sandbox.entity.attributes["environment"] == "sandbox-7"
    assert not [e for e in sandbox.related if e.type == "environment"]
    assert not [r for r in sandbox.relationships if r.type == "runs_in"]


def test_the_company_s_tag_keys_say_the_application_and_the_criticality() -> None:
    instance = _instance(
        {"Produit": "Billing", "Impact": "high", "app": "billing-api"},
        Mapping(tag_keys=TagKeys(application=["produit"], criticality=["impact"])),
    )

    assert ("service:billing-api", "part_of", "application:billing") in _edges(instance)
    assert (
        instance.entity.attributes["criticality"],
        instance.entity.attributes["criticality_confidence"],
    ) == ("high", 0.95)


# ── PagerDuty: dependencies and business services ────────────────────────────


def test_a_pagerduty_service_depends_on_the_services_pagerduty_says() -> None:
    payload = {
        **PAGERDUTY_CHECKOUT,
        "dependencies": [{"id": "PSEARCH", "name": "Search", "type": "technical"}],
    }

    service = _normalised(SourceKind.PAGERDUTY, C.SERVICES, payload)

    assert ("service:checkout", "depends_on", "service:search") in _edges(service)
    assert "depends_on" not in service.entity.attributes


def test_a_pagerduty_business_service_is_an_application_with_its_services() -> None:
    payload = {
        **ONLINE_SHOP,
        "dependencies": [
            {"id": "PCHKOUT", "name": "Checkout", "type": "technical"},
            {"id": "PSEARCH", "name": "Search", "type": "technical"},
            {"id": "PBPAY01", "name": "Payments", "type": "business"},
        ],
    }

    shop = _normalised(SourceKind.PAGERDUTY, C.SERVICES, payload)

    assert (shop.entity.type, shop.entity.key) == ("application", "application:online-shop")
    assert {
        ("service:checkout", "part_of", "application:online-shop"),
        ("service:search", "part_of", "application:online-shop"),
        ("application:online-shop", "depends_on", "application:payments"),
        ("application:online-shop", "owned_by", "team:commerce"),
    } <= _edges(shop)
    assert shop.entity.attributes["point_of_contact"] == "shop-leads@acme.test"
    assert "kind" not in shop.entity.attributes


# ── the Datadog service catalog ──────────────────────────────────────────────


def test_a_catalog_service_says_its_owner_application_tier_and_lifecycle() -> None:
    billing = _normalised(SourceKind.DATADOG, C.SERVICES, BILLING_V22)

    attributes = billing.entity.attributes
    assert (billing.entity.type, billing.entity.key) == ("service", "service:billing-api")
    assert {
        ("service:billing-api", "owned_by", "team:payments"),
        ("service:billing-api", "part_of", "application:billing"),
    } <= _edges(billing)
    assert (attributes["criticality"], attributes["criticality_raw"]) == ("critical", "1")
    assert (attributes["stage"], attributes["stage_raw"]) == ("production", "production")
    assert attributes["service_type"] == "web"
    assert attributes["languages"] == ["python"]
    # Read, and kept on LEKA's scales — not twice, not as enrichment's own
    # `lifecycle` word.
    assert "tier" not in attributes
    assert "lifecycle" not in attributes


def test_a_catalog_v3_service_depends_on_services_and_is_part_of_its_system() -> None:
    ledger = _normalised(SourceKind.DATADOG, C.SERVICES, LEDGER_V3)

    assert {
        ("service:ledger", "depends_on", "service:postgres-ledger"),
        ("service:ledger", "depends_on", "service:billing-api"),
        ("service:ledger", "part_of", "application:billing"),
        ("service:ledger", "owned_by", "team:finance-platform"),
    } <= _edges(ledger)
    assert ledger.entity.attributes["stage"] == "deprecated"
    assert ledger.entity.attributes["criticality"] == "high"


def test_a_catalog_word_leka_does_not_know_is_kept_and_said() -> None:
    odd = {**BILLING_V22, "attributes": {"schema": {"dd-service": "odd", "tier": "gold"}}}
    odd["attributes"]["schema"]["lifecycle"] = "hibernating"

    record = _normalised(SourceKind.DATADOG, C.SERVICES, odd)

    assert record.entity.attributes["criticality"] == "gold"
    assert record.entity.attributes["stage"] == "hibernating"
    assert "unknown criticality: kept as the catalogue wrote it" in record.diagnostics
    assert "unknown lifecycle: kept as the catalogue wrote it" in record.diagnostics


# ── a custom source: a CMDB, a Backstage catalogue ───────────────────────────


def _custom(entity: str, title: str, metadata: dict[str, Any]) -> NormalisedRecord:
    return _normalised(
        SourceKind.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": "catalogue",
            "entity": entity,
            "fields": {"id": title, "title": title, "metadata": metadata},
        },
        external_id=f"catalogue:{title}",
    )


def test_a_custom_source_declares_applications_as_a_catalogue_does() -> None:
    billing = _custom(
        "application",
        "Billing",
        {
            "team": "Payments",
            "criticality": "Tier 1",
            "lifecycle": "GA",
            "environments": "prod, staging",
            "services": ["billing-api", "ledger"],
        },
    )

    assert (billing.entity.type, billing.entity.key) == ("application", "application:billing")
    assert {
        ("application:billing", "owned_by", "team:payments"),
        ("service:billing-api", "part_of", "application:billing"),
        ("service:ledger", "part_of", "application:billing"),
        ("application:billing", "runs_in", "environment:production"),
        ("application:billing", "runs_in", "environment:staging"),
    } <= _edges(billing)
    assert (billing.entity.attributes["criticality"], billing.entity.attributes["stage"]) == (
        "critical",
        "production",
    )


def test_a_custom_source_s_service_depends_on_what_its_admin_mapped() -> None:
    api = _custom(
        "service",
        "billing-api",
        {"application": "Billing", "dependencies": "ledger,payments-gateway", "owner": "payments"},
    )

    assert {
        ("service:billing-api", "part_of", "application:billing"),
        ("service:billing-api", "depends_on", "service:ledger"),
        ("service:billing-api", "depends_on", "service:payments-gateway"),
        ("service:billing-api", "owned_by", "team:payments"),
    } <= _edges(api)


def test_every_tool_names_one_service_by_one_key() -> None:
    pagerduty = _normalised(
        SourceKind.PAGERDUTY, C.SERVICES, {**PAGERDUTY_CHECKOUT, "name": "Billing API"}
    )
    datadog = _normalised(SourceKind.DATADOG, C.SERVICES, BILLING_V22)
    tagged = _instance({"service": "billing_api"})
    custom = _custom("service", "Billing-API", {})

    keys = {
        pagerduty.entity.key,
        datadog.entity.key,
        next(k for k, t in _related(tagged).items() if t == "service"),
        custom.entity.key,
    }
    # One key: resolution makes one entity of the four.
    assert keys == {"service:billing-api"}
