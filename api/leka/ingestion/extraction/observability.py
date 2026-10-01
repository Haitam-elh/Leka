"""Observability: Datadog's monitors, events, incidents, metrics, logs and
service catalog; PagerDuty's services, business services and incidents;
Grafana's dashboards, alert rules and annotations; Splunk's alerts, the
alerts that fired and dashboards; Kibana's alert rules, cases and
dashboards.

What an operations question needs, the same way whatever the tool: the
record's `title`, its `state` (a monitor's, an incident's, a log's
status), when it happened, its text, and technical `signals` — `service`,
`env`, `host`, `tags` ('key:value', as Datadog writes them), `severity`.
Datadog's own id stays the record's id, and its timestamp its date.

The payloads are the ones leka/connectors/{datadog,pagerduty,grafana,
splunk,kibana} store: the APIs' answers — Datadog's and Grafana's with `web_url` beside
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
SPLUNK = SourceKind.SPLUNK
KIBANA = SourceKind.KIBANA
# Splunk's alert severities, 1 to 6, in its words.
SPLUNK_SEVERITIES = {1: "info", 2: "low", 3: "medium", 4: "high", 5: "critical", 6: "fatal"}


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


# ── Splunk ───────────────────────────────────────────────────────────────────


@strategy("splunk.alerts", 1, (SPLUNK, C.ALERTS))
def splunk_alert(p: Payload) -> Extracted:
    """A saved search that alerts: its search, when it runs, how severe it
    says it is, what it does when it fires."""
    c = dig(p, "content")
    return Extracted(
        title=required(p, "name"),
        state="disabled" if _yes(dig(c, "disabled")) else "enabled",
        updated_at=when(p, "updated"),
        content=content("description", string(c, "description")),
        references=ref("creator", "person", name=string(p, "author")),
        metadata={
            "search": string(c, "search"),
            "schedule": string(c, "cron_schedule"),
            "condition": lower(c, "alert_type"),
            "severity": _splunk_severity(dig(c, "alert.severity")),
            "actions": [a.strip() for a in (string(c, "actions") or "").split(",") if a.strip()],
            "owner": string(p, "acl", "owner"),
        },
        signals={"app": string(p, "acl", "app")},
    )


@strategy("splunk.events", 1, (SPLUNK, C.EVENTS))
def splunk_fired_alert(p: Payload) -> Extracted:
    """An alert that fired: which search, when, how severe."""
    c = dig(p, "content")
    fired = _from_seconds(number(c, "trigger_time"))
    return Extracted(
        title=string(c, "savedsearch_name") or required(p, "name"),
        state="triggered",
        created_at=fired,
        updated_at=fired or when(p, "updated"),
        metadata={
            "severity": _splunk_severity(dig(c, "severity")),
            "sid": string(c, "sid"),
            "expires_at": _iso(_from_seconds(number(c, "expiration_time"))),
        },
        signals={"app": string(c, "app") or string(p, "acl", "app")},
    )


@strategy("splunk.dashboards", 1, (SPLUNK, C.DASHBOARDS))
def splunk_dashboard(p: Payload) -> Extracted:
    c = dig(p, "content")
    return Extracted(
        title=string(c, "label") or required(p, "name"),
        updated_at=when(p, "updated"),
        content=content("description", string(c, "description")),
        references=ref("creator", "person", name=string(p, "author")),
        metadata={"name": string(p, "name"), "owner": string(p, "acl", "owner")},
        signals={"app": string(p, "acl", "app")},
    )


def _splunk_severity(value: object) -> str | None:
    try:
        return SPLUNK_SEVERITIES.get(int(str(value)))
    except ValueError:
        return None


def _yes(value: object) -> bool:
    return value is True or value == 1 or str(value).strip().lower() in ("1", "true")


def _from_seconds(value: int | float | None) -> datetime | None:
    """Splunk's times: seconds since the epoch."""
    if value is None or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


# ── Kibana ───────────────────────────────────────────────────────────────────


@strategy("kibana.alerts", 1, (KIBANA, C.ALERTS))
def kibana_rule(p: Payload) -> Extracted:
    """An alerting rule: what kind, on or off, how its last run went."""
    tags = strings(p, "tags")
    enabled = flag(p, "enabled")
    return Extracted(
        title=required(p, "name"),
        url=string(p, "web_url"),
        state=lower(p, "execution_status", "status")
        or lower(p, "last_run", "outcome")
        or (None if enabled is None else "enabled" if enabled else "disabled"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at"),
        references=ref("creator", "person", name=string(p, "created_by")),
        metadata={
            "rule_type": string(p, "rule_type_id"),
            "consumer": string(p, "consumer"),
            "enabled": enabled,
            "interval": string(p, "schedule", "interval"),
            "last_run_at": _iso(when(p, "execution_status", "last_execution_date")),
        },
        signals={**_signals(tags), "space": string(p, "space")},
    )


@strategy("kibana.incidents", 1, (KIBANA, C.INCIDENTS))
def kibana_case(p: Payload) -> Extracted:
    """A case — Kibana's incident: its status, its severity, who opened it,
    its tags."""
    tags = strings(p, "tags")
    return Extracted(
        title=required(p, "title"),
        url=string(p, "web_url"),
        state=lower(p, "status"),
        created_at=when(p, "created_at"),
        updated_at=when(p, "updated_at") or when(p, "created_at"),
        content=content("description", string(p, "description"), "markdown"),
        references=ref(
            "creator",
            "person",
            external_id=dig(p, "created_by", "username"),
            name=dig(p, "created_by", "full_name") or dig(p, "created_by", "username"),
            email=dig(p, "created_by", "email"),
        ),
        metadata={
            "severity": lower(p, "severity"),
            "owner": string(p, "owner"),
            "comments": number(p, "totalComment"),
            "closed_at": _iso(when(p, "closed_at")),
        },
        signals={
            **_signals(tags),
            # The services it affects, as the incidents of the other tools
            # name them: its `service:` tags.
            "services": [s for s in (_tag(tags, "service"),) if s],
            "space": string(p, "space"),
        },
    )


@strategy("kibana.dashboards", 1, (KIBANA, C.DASHBOARDS))
def kibana_dashboard(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "attributes", "title"),
        url=string(p, "web_url"),
        updated_at=when(p, "updated_at"),
        content=content("description", string(p, "attributes", "description")),
        signals={"space": string(p, "space")},
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
