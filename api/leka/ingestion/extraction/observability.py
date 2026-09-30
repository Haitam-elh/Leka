"""Observability: Datadog's monitors, events, incidents, metrics, logs and
service catalog; PagerDuty's services, business services and incidents;
Grafana's dashboards, alert rules and annotations.

What an operations question needs, the same way whatever the tool: the
record's `title`, its `state` (a monitor's, an incident's, a log's
status), when it happened, its text, and technical `signals` — `service`,
`env`, `host`, `tags` ('key:value', as Datadog writes them), `severity`.
Datadog's own id stays the record's id, and its timestamp its date.

The payloads are the ones leka/connectors/{datadog,pagerduty,grafana}
store: the APIs' answers — Datadog's and Grafana's with `web_url` beside
them, Datadog's incidents with their people resolved, Grafana's rules with
their group and folder.
"""

from __future__ import annotations

from datetime import UTC, datetime

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted
from leka.ingestion.extraction.engine import MalformedPayloadError, Payload, strategy
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
GRAFANA = SourceKind.GRAFANA


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


@strategy("datadog.services", 1, (DATADOG, C.SERVICES))
def datadog_service(p: Payload) -> Extracted:
    """A service as its team wrote it in the catalog — the schemas v2 to
    v2.2 (`dd-service`, `team`, `application`…) or v3 (`metadata`,
    `spec`): its owner, its application, its tier and lifecycle, its kind
    and languages, its links, what it depends on (LEKA-362)."""
    schema = dig(p, "attributes", "schema")
    if not isinstance(schema, dict):
        raise MalformedPayloadError("missing field 'attributes.schema'")
    v3 = isinstance(schema.get("metadata"), dict)
    about = schema["metadata"] if v3 else schema
    spec = dig(schema, "spec") if v3 else schema
    name = string(schema, "metadata", "name") if v3 else string(schema, "dd-service")
    if not name:
        raise MalformedPayloadError("missing field 'dd-service'")
    teams = [
        *[t for t in (string(about, "owner"), string(about, "team")) if t],
        *strings(about, "additionalOwners", key="name"),
    ]
    systems = [s.removeprefix("system:") for s in strings(spec, "componentOf")]
    links = dig(about, "links")
    return Extracted(
        title=name.lower(),
        content=content("description", string(about, "description")),
        updated_at=when(p, "attributes", "meta", "last-modified-time"),
        metadata={
            "display_name": string(about, "displayName"),
            "tier": string(spec, "tier"),
            "lifecycle": lower(spec, "lifecycle"),
            "service_type": lower(spec, "type"),
            "languages": strings(spec, "languages"),
            **_links(links if isinstance(links, list) else []),
        },
        signals={
            "teams": list(dict.fromkeys(teams)),
            "application": string(schema, "application") or next(iter(systems), None),
            "depends_on": _depends_on(strings(spec, "dependsOn")),
        },
    )


def _depends_on(references: list[str]) -> list[str]:
    """The services among what v3 says a service depends on: `service:x`
    — a datastore or a queue is named in Datadog's words, not a key LEKA
    shares with another tool."""
    found = []
    for reference in references:
        kind, _, name = reference.rpartition(":")
        if kind in ("", "service") and name:
            found.append(name.lower())
    return list(dict.fromkeys(found))


def _links(links: list[object]) -> dict[str, str]:
    """A catalog's links, the first of each kind that says where to look:
    `runbook_url`, `repository_url`, `dashboard_url`, `docs_url`."""
    kinds = {"runbook": "runbook_url", "repo": "repository_url", "dashboard": "dashboard_url"}
    kinds |= {"doc": "docs_url", "docs": "docs_url"}
    found: dict[str, str] = {}
    for link in links:
        kind = kinds.get(str(dig(link, "type") or "").lower())
        url = string(link, "url")
        if kind and url and kind not in found:
            found[kind] = url
    return found


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


@strategy("pagerduty.services", 2, (PAGERDUTY, C.SERVICES))
def pagerduty_service(p: Payload) -> Extracted:
    """A technical service — its team, its escalation policy, the services
    it depends on — or a business service: what one of the company's
    applications is to PagerDuty, with the services that support it
    (LEKA-362)."""
    dependencies = dig(p, "dependencies")
    listed = dependencies if isinstance(dependencies, list) else []
    technical = [str(d["name"]) for d in listed if d.get("type") == "technical" and d.get("name")]
    business = [str(d["name"]) for d in listed if d.get("type") == "business" and d.get("name")]
    if p.get("type") == "business_service":
        team = string(p, "team", "summary")
        return Extracted(
            title=required(p, "name"),
            url=string(p, "html_url"),
            content=content("description", string(p, "description")),
            metadata={"point_of_contact": string(p, "point_of_contact")},
            signals={
                "kind": "application",
                "teams": [team] if team else [],
                "services": technical,
                "depends_on": business,
            },
        )
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
            "depends_on": technical,
        },
    )


@strategy("grafana.dashboards", 1, (GRAFANA, C.DASHBOARDS))
def grafana_dashboard(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "title"),
        url=string(p, "web_url"),
        metadata={"uid": string(p, "uid"), "folder": string(p, "folderTitle")},
        signals={"tags": sorted(strings(p, "tags"))},
    )


@strategy("grafana.alerts", 1, (GRAFANA, C.ALERTS))
def grafana_rule(p: Payload) -> Extracted:
    labels = dig(p, "labels")
    label_tags = sorted(f"{k}:{v}" for k, v in labels.items()) if isinstance(labels, dict) else []
    return Extracted(
        title=required(p, "name"),
        state=lower(p, "state"),
        updated_at=when(p, "lastEvaluation"),
        content=[
            *content("summary", string(p, "annotations", "summary")),
            *content("description", string(p, "annotations", "description")),
        ],
        metadata={
            "query": string(p, "query"),
            "health": lower(p, "health"),
            "group": string(p, "group"),
            "folder": string(p, "folder"),
        },
        signals={
            "tags": label_tags,
            "service": string(labels, "service"),
            "env": string(labels, "env") or string(labels, "environment"),
            "team": string(labels, "team"),
            "severity": lower(labels, "severity"),
        },
    )


@strategy("grafana.events", 1, (GRAFANA, C.EVENTS))
def grafana_annotation(p: Payload) -> Extracted:
    text = string(p, "text")
    happened = _from_ms(number(p, "time"))
    tags = strings(p, "tags")
    return Extracted(
        title=first_line(text) or f"annotation {required(p, 'id')}",
        state=lower(p, "newState"),
        created_at=happened,
        updated_at=_from_ms(number(p, "updated")) or happened,
        content=content("text", text),
        metadata={
            "dashboard_uid": string(p, "dashboardUID"),
            "panel_id": number(p, "panelId"),
            "ends_at": _iso(_from_ms(number(p, "timeEnd"))),
        },
        signals={"tags": sorted(tags)},
    )


def _from_ms(value: int | float | None) -> datetime | None:
    """Grafana's times: milliseconds since the epoch."""
    if value is None or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


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
