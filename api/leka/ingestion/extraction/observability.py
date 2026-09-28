"""Observability: Datadog's monitors, events, incidents, metrics and logs;
PagerDuty's services and incidents.

What an operations question needs, the same way whatever the tool: the
record's `title`, its `state` (a monitor's, an incident's, a log's
status), when it happened, its text, and technical `signals` — `service`,
`env`, `host`, `tags` ('key:value', as Datadog writes them), `severity`.
Datadog's own id stays the record's id, and its timestamp its date.

The payloads are the ones leka/connectors/{datadog,pagerduty} store: the
APIs' answers — Datadog's with `web_url` beside them, and an incident's
people resolved.
"""

from __future__ import annotations

from datetime import UTC, datetime

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import (
    content,
    dig,
    first_line,
    flag,
    lower,
    number,
    people,
    ref,
    required,
    string,
    strings,
    when,
)

C = Capability
DATADOG = SourceKind.DATADOG
PAGERDUTY = SourceKind.PAGERDUTY


@strategy("datadog.alerts", 1, (DATADOG, C.ALERTS))
def datadog_monitor(p: Payload) -> Extracted:
    tags = strings(p, "tags")
    return Extracted(
        title=required(p, "name"),
        url=string(p, "web_url"),
        state=lower(p, "overall_state"),
        created_at=when(p, "created"),
        updated_at=when(p, "modified"),
        content=content("message", string(p, "message"), "markdown"),
        references=ref(
            "creator", "person", name=dig(p, "creator", "name"), email=dig(p, "creator", "email")
        ),
        metadata={
            "id": number(p, "id"),
            "type": lower(p, "type"),
            "query": string(p, "query"),
            "priority": number(p, "priority"),
        },
        signals=_signals(tags),
    )


@strategy("datadog.events", 1, (DATADOG, C.EVENTS))
def datadog_event(p: Payload) -> Extracted:
    inner = dig(p, "attributes", "attributes")
    message = string(p, "attributes", "message")
    tags = strings(p, "attributes", "tags")
    happened = when(p, "attributes", "timestamp")
    return Extracted(
        title=string(inner, "title") or first_line(message) or required(p, "id"),
        state=lower(inner, "status"),
        created_at=happened,
        updated_at=happened,
        content=content("message", message, "markdown"),
        metadata={
            "priority": string(inner, "priority"),
            "aggregation_key": string(inner, "aggregation_key"),
            "monitor_id": number(inner, "monitor_id"),
        },
        signals={
            **_signals(tags),
            "service": string(inner, "service") or _tag(tags, "service"),
            "host": string(inner, "hostname") or _tag(tags, "host"),
            "source": lower(inner, "source_type_name"),
        },
    )


@strategy("datadog.incidents", 1, (DATADOG, C.INCIDENTS))
def datadog_incident(p: Payload) -> Extracted:
    a = dig(p, "attributes")
    services = strings(a, "fields", "services", "value")
    return Extracted(
        title=required(a, "title"),
        url=string(p, "web_url"),
        state=lower(a, "state"),
        created_at=when(a, "created"),
        updated_at=when(a, "modified"),
        content=content("impact", string(a, "customer_impact_scope")),
        references=[
            *ref(
                "commander",
                "person",
                name=dig(p, "people", "commander_user", "name"),
                email=dig(p, "people", "commander_user", "email"),
            ),
            *ref(
                "creator",
                "person",
                name=dig(p, "people", "created_by_user", "name"),
                email=dig(p, "people", "created_by_user", "email"),
            ),
        ],
        metadata={
            "public_id": number(a, "public_id"),
            "severity": string(a, "severity"),
            "customer_impacted": flag(a, "customer_impacted"),
            "resolved_at": _iso(when(a, "resolved")),
            "time_to_resolve": number(a, "time_to_resolve"),
        },
        signals={"services": services, "service": services[0] if services else None},
    )


@strategy("datadog.metrics", 1, (DATADOG, C.METRICS))
def datadog_metric(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "id"),
        created_at=when(p, "attributes", "created_at"),
        updated_at=when(p, "attributes", "modified_at"),
        metadata={"metric_type": lower(p, "attributes", "metric_type")},
        signals={"tags": strings(p, "attributes", "tags")},
    )


@strategy("datadog.logs", 1, (DATADOG, C.LOGS))
def datadog_log(p: Payload) -> Extracted:
    a = dig(p, "attributes")
    message = string(a, "message")
    tags = strings(a, "tags")
    happened = when(a, "timestamp")
    return Extracted(
        title=first_line(message) or required(p, "id"),
        url=string(p, "web_url"),
        state=lower(a, "status"),
        created_at=happened,
        updated_at=happened,
        content=content("message", message),
        signals={
            **_signals(tags),
            "service": string(a, "service") or _tag(tags, "service"),
            "host": string(a, "host") or _tag(tags, "host"),
        },
    )


@strategy("pagerduty.incidents", 1, (PAGERDUTY, C.INCIDENTS))
def pagerduty_incident(p: Payload) -> Extracted:
    assignments = dig(p, "assignments")
    assignees = [dig(a, "assignee") for a in assignments] if isinstance(assignments, list) else []
    return Extracted(
        title=required(p, "title"),
        url=string(p, "html_url"),
        state=lower(p, "status"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at") or when(p, "last_status_change_at"),
        content=content("description", string(p, "description")),
        references=[
            *people("assignee", assignees, id_key="id", name_key="summary"),
            *ref(
                "service",
                "service",
                external_id=dig(p, "service", "id"),
                name=dig(p, "service", "summary"),
            ),
        ],
        metadata={
            "incident_number": number(p, "incident_number"),
            "urgency": lower(p, "urgency"),
            "priority": string(p, "priority", "summary"),
            "resolved_at": _iso(when(p, "resolved_at")),
        },
        signals={
            "service": string(p, "service", "summary"),
            "escalation_policy": string(p, "escalation_policy", "summary"),
            "teams": strings(p, "teams", key="summary"),
        },
    )


@strategy("pagerduty.services", 1, (PAGERDUTY, C.SERVICES))
def pagerduty_service(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        url=string(p, "html_url"),
        state=lower(p, "status"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at"),
        content=content("description", string(p, "description")),
        metadata={"last_incident_at": _iso(when(p, "last_incident_timestamp"))},
        signals={
            "escalation_policy": string(p, "escalation_policy", "summary"),
            "teams": strings(p, "teams", key="summary"),
        },
    )


def _signals(tags: list[str]) -> dict[str, str | list[str] | None]:
    """What Datadog's reserved tags say, and the tags themselves."""
    return {
        "tags": sorted(tags),
        "service": _tag(tags, "service"),
        "env": _tag(tags, "env"),
        "team": _tag(tags, "team"),
    }


def _tag(tags: list[str], key: str) -> str | None:
    """The value of the first 'key:value' tag with this key."""
    prefix = f"{key}:"
    return next((tag[len(prefix) :] for tag in tags if tag.startswith(prefix)), None)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat() if moment else None
