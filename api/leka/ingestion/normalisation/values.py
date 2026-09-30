"""Canonical values: one word for one state, one clock, one scale.

A merge request "opened", a pull request "open" and a Jira issue in a "new"
status category are all `open`; an EC2 instance "running", an Azure VM
"Succeeded" and a GCE instance "RUNNING" are all `running`. The vendor's own
word stays beside it (`state_raw`): nothing is lost, and a state no table
knows is kept as it is, with a diagnostic.
"""

from __future__ import annotations

from datetime import UTC, datetime

# Work items: open, in_progress, closed, merged (a pull request's own end).
WORK_STATES = {
    "open": "open",
    "opened": "open",
    "new": "open",
    "reopened": "open",
    "on hold": "open",
    "to do": "open",
    "todo": "open",
    "backlog": "open",
    "in progress": "in_progress",
    "in review": "in_progress",
    "indeterminate": "in_progress",
    "closed": "closed",
    "done": "closed",
    "resolved": "closed",
    "declined": "closed",
    "superseded": "closed",
    "locked": "closed",
    "invalid": "closed",
    "duplicate": "closed",
    "wontfix": "closed",
    "merged": "merged",
    # Monday's default labels, and what other tools call being done.
    "working on it": "in_progress",
    "stuck": "in_progress",
    "complete": "closed",
    "completed": "closed",
}
# A tool's own classes of state, surer than a status name any team renames:
# Jira's three categories, Linear's workflow types, ClickUp's status types.
STATUS_CATEGORIES = {
    "new": "open",
    "indeterminate": "in_progress",
    "done": "closed",
    "backlog": "open",
    "triage": "open",
    "unstarted": "open",
    "started": "in_progress",
    "completed": "closed",
    "canceled": "closed",
    "cancelled": "closed",
    "open": "open",
    "custom": "in_progress",
    "closed": "closed",
}

# Cloud resources: running, starting, stopping, stopped, deleting, failed.
RESOURCE_STATES = {
    "running": "running",
    "available": "running",
    "active": "running",
    "succeeded": "running",
    "inservice": "running",
    "runnable": "running",
    "ready": "running",
    "pending": "starting",
    "creating": "starting",
    "provisioning": "starting",
    "starting": "starting",
    "staging": "starting",
    "updating": "starting",
    "modifying": "starting",
    "stopping": "stopping",
    "shutting-down": "stopping",
    "suspending": "stopping",
    "stopped": "stopped",
    "terminated": "stopped",
    "suspended": "stopped",
    "inactive": "stopped",
    "deleting": "deleting",
    "deleted": "deleting",
    "failed": "failed",
    "error": "failed",
    "degraded": "failed",
}

# Priorities on one scale: highest, high, medium, low, lowest.
PRIORITIES = {
    "highest": "highest",
    "blocker": "highest",
    "critical": "highest",
    "urgent": "highest",
    "high": "high",
    "major": "high",
    "medium": "medium",
    "normal": "medium",
    "low": "low",
    "minor": "low",
    "lowest": "lowest",
    "trivial": "lowest",
    # Incident severities (Datadog's SEV-n) and priorities (PagerDuty's Pn).
    "sev-0": "highest",
    "sev-1": "highest",
    "sev-2": "high",
    "sev-3": "medium",
    "sev-4": "low",
    "sev-5": "lowest",
    "p1": "highest",
    "p2": "high",
    "p3": "medium",
    "p4": "low",
    "p5": "lowest",
}

# Where a service or an application is in its life, as its catalogue says
# (LEKA-362): experimental, production, deprecated, retired.
STAGES = {
    "experimental": "experimental",
    "alpha": "experimental",
    "beta": "experimental",
    "pilot": "experimental",
    "poc": "experimental",
    "prototype": "experimental",
    "incubating": "experimental",
    "production": "production",
    "prod": "production",
    "ga": "production",
    "live": "production",
    "stable": "production",
    "deprecated": "deprecated",
    "sunset": "deprecated",
    "sunsetting": "deprecated",
    "legacy": "deprecated",
    "retired": "retired",
    "decommissioned": "retired",
    "end of life": "retired",
    "end-of-life": "retired",
    "eol": "retired",
}

# An incident's life on the work scale: open, being handled, over.
INCIDENT_STATES = {
    "triggered": "open",
    "active": "open",
    "open": "open",
    "acknowledged": "in_progress",
    "stable": "in_progress",
    "investigating": "in_progress",
    "mitigated": "in_progress",
    "resolved": "closed",
    "closed": "closed",
    "completed": "closed",
}


def work_state(raw: str | None, *, category: str | None = None) -> tuple[str | None, bool]:
    """(canonical state, known). Jira's status category wins over its name."""
    if category and category in STATUS_CATEGORIES:
        return STATUS_CATEGORIES[category], True
    return _lookup(WORK_STATES, raw)


def incident_state(raw: str | None) -> tuple[str | None, bool]:
    return _lookup(INCIDENT_STATES, raw)


def resource_state(raw: str | None) -> tuple[str | None, bool]:
    return _lookup(RESOURCE_STATES, raw)


def priority(raw: str | None) -> tuple[str | None, bool]:
    return _lookup(PRIORITIES, raw)


def stage(raw: str | None) -> tuple[str | None, bool]:
    return _lookup(STAGES, raw)


def utc(value: datetime | str | None) -> str | None:
    """Any aware date as ISO 8601 in UTC, to the second: '2026-09-20T08:00:00Z'.
    A naive one is taken as UTC — no vendor here sends one."""
    if value is None:
        return None
    when = datetime.fromisoformat(value) if isinstance(value, str) else value
    when = when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
    return when.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def name(value: str | None) -> str | None:
    """A display name, one way: its spaces collapsed, at most 500 characters."""
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned[:500] or None


def _lookup(table: dict[str, str], raw: str | None) -> tuple[str | None, bool]:
    if raw is None:
        return None, True
    word = raw.strip().lower().replace("_", " ")
    if word in table:
        return table[word], True
    return raw.strip().lower(), False
