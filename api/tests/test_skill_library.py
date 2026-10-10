"""The enterprise skill library (LEKA-401), judged — pure, no database.

What these protect:
- Ten skills, one per domain, each on the common contract: its input and
  output declared, it reads (never acts), the kinds of things it reads, what
  must be connected when it needs a source, its limits said; each output
  says what it read and what it concluded, as signals.
- What each concludes, from what the company model holds:
  - delivery: deployment frequency, change failure rate (failed, or followed
    by an incident its source ties to it), time to recover, DORA's tiers;
  - incidents: one severity scale whatever the tool said; open, recurring,
    severe, slow to resolve;
  - infrastructure: by provider, kind, region, state; the unowned, the
    public, the failed, the not running;
  - security: what is public and critical, public and unowned, public
    repositories, secrets and personal data stored;
  - data, documentation, architecture, testing, a change, a repository:
    each signal from the facts that call for it, and only those.
- An agent is offered a skill it names only when the skill reads nothing the
  agent may not.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from leka.capabilities import Assessed, Definition, Kind, Lifecycle, all_skills
from leka.capabilities.skills import agent_skill_tools
from leka.intelligence import library
from leka.intelligence.library import (
    LIBRARY,
    Activity,
    BlastRadius,
    ChangeReview,
    Citer,
    DataLandscape,
    DocumentationCoverageSaid,
    Exposed,
    Gap,
    IncidentSaid,
    KindCoverage,
    Named,
    Reach,
    RepositoryProfile,
    ScopeToTest,
    SecurityPosture,
    Sensitive,
    SensitiveObject,
    Store,
    ToTest,
    delivery_of,
    failure_tier,
    frequency_tier,
    history_of,
    inventory_of,
    judge_change,
    judge_coverage,
    judge_data,
    judge_delivery,
    judge_history,
    judge_inventory,
    judge_posture,
    judge_radius,
    judge_repository,
    judge_scope,
    recovery_tier,
    severity_of,
)
from leka.knowledge import DeploymentRead, EntityType, IncidentRead, InfrastructureRead

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
SINCE = NOW - timedelta(days=28)


def _brief(name: str, type_: str = "service") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "key": f"{type_}:{name}",
        "name": name,
        "type": type_,
        "lifecycle": "active",
    }


def incident(
    name: str,
    *,
    severity: str | None = None,
    priority: str | None = None,
    state: str = "closed",
    minutes: int | None = 60,
    causes: tuple[str, ...] = (),
) -> IncidentRead:
    return IncidentRead.model_validate(
        {
            "id": str(uuid.uuid4()),
            "key": f"incident:{name}",
            "name": name,
            "lifecycle": "active",
            "url": None,
            "tools": ["pagerduty"],
            "state": state,
            "priority": priority,
            "severity": severity,
            "urgency": None,
            "opened_at": NOW - timedelta(days=3),
            "acknowledged_at": None,
            "resolved_at": None,
            "time_to_acknowledge_minutes": None,
            "duration_minutes": minutes,
            "affects": [],
            "commander": None,
            "assignees": [],
            "causes": [_brief(c, "deployment") for c in causes],
        }
    )


def deployment(
    name: str, *, days_ago: int, state: str = "succeeded", incidents: int = 0
) -> DeploymentRead:
    return DeploymentRead.model_validate(
        {
            "id": str(uuid.uuid4()),
            "key": f"deployment:{name}",
            "name": name,
            "lifecycle": "active",
            "url": None,
            "tools": ["github"],
            "state": state,
            "environment": "production",
            "production": True,
            "ref": name,
            "sha": None,
            "deployed_at": NOW - timedelta(days=days_ago),
            "started_at": None,
            "finished_at": None,
            "duration_minutes": None,
            "repository": None,
            "services": [],
            "deployer": None,
            "incident_count": incidents,
        }
    )


def resource(
    name: str,
    *,
    state: str | None = "running",
    exposure: str | None = None,
    criticality: str | None = None,
    owned: bool = True,
    provider: str = "aws",
) -> InfrastructureRead:
    return InfrastructureRead.model_validate(
        {
            "id": str(uuid.uuid4()),
            "type": "infra_resource",
            "key": f"aws:{name}",
            "name": name,
            "lifecycle": "active",
            "provider": provider,
            "resource_kind": "instance",
            "resource_class": "compute",
            "resource_type": "ec2:instance",
            "state": state,
            "account": None,
            "resource_group": None,
            "region": "eu-west-3",
            "zone": None,
            "environment": None,
            "exposure": exposure,
            "criticality": (
                {"level": criticality, "origin": "source", "confidence": None, "raw": None}
                if criticality
                else None
            ),
            "services": [_brief("billing-api")] if owned else [],
            "applications": [],
            "owners": [],
            "network": None,
            "cluster": None,
            "dependencies": 0,
            "dependents": 0,
            "last_seen_at": None,
        }
    )


def named(name: str, type_: str = "service") -> Named:
    return Named(id=f"entity:{uuid.uuid4()}", name=name, type=type_)


def codes(signals: list[Any]) -> dict[str, str]:
    return {s.code: s.level for s in signals}


# ── the library ──────────────────────────────────────────────────────────────


def test_ten_skills_one_per_domain_each_on_the_common_contract() -> None:
    keys = [s.key for s in LIBRARY]
    assert keys == [
        "repository-profile",
        "change-review",
        "test-scope",
        "security-posture",
        "documentation-coverage",
        "blast-radius",
        "incident-history",
        "infrastructure-inventory",
        "data-landscape",
        "delivery-metrics",
    ]
    registered = {s.key for s in all_skills()}
    known = {t.value for t in EntityType}
    for skill in LIBRARY:
        assert skill.key in registered
        assert skill.effect == "read"
        assert issubclass(skill.output, Assessed), skill.key
        assert skill.reads and set(skill.reads) <= known, skill.key
        assert skill.limitations, skill.key
        contract = skill.contract()
        assert contract["input"]["type"] == "object"
        assert {"signals", "cited"} <= set(contract["output"]["properties"]), skill.key
    needs = {s.key: s.sources for s in LIBRARY if s.sources}
    assert needs == {
        "repository-profile": (("github", "gitlab", "bitbucket"),),
        "documentation-coverage": (
            ("confluence", "notion", "microsoft_365", "google_workspace", "guru", "slab"),
        ),
        "infrastructure-inventory": (("aws", "azure", "gcp"),),
        "data-landscape": (
            ("postgresql", "mysql", "mariadb", "sqlserver", "oracle", "mongodb", "supabase"),
        ),
    }


# ── release and deployment ───────────────────────────────────────────────────


def test_delivery_in_dora_s_terms() -> None:
    deployments = [deployment(f"v1.{i}", days_ago=2 + 3 * i) for i in range(8)]
    deployments[0] = deployment("v1.0", days_ago=2, state="failed")
    deployments[1] = deployment("v1.1", days_ago=5, incidents=1)
    incidents = [
        incident("slow", minutes=30),
        incident("down", minutes=90),
        incident("open", state="open", minutes=None),
    ]
    metrics = delivery_of(
        deployments,
        incidents,
        of="Billing API",
        environment="production",
        since=SINCE,
        now=NOW,
        days=28,
    )
    assert (metrics.deployments, metrics.per_week, metrics.failed) == (8, 2.0, 1)
    assert (metrics.followed_by_incident, metrics.change_failure_rate) == (1, 0.25)
    # Of the closed ones: the median.
    assert metrics.mttr_minutes == 60
    assert metrics.last_deployment_at == NOW - timedelta(days=2)
    assert metrics.days_since_last == 2
    assert metrics.tiers.model_dump() == {
        "frequency": "high",
        "failure_rate": "low",
        "recovery": "high",
    }
    assert [d.name for d in metrics.latest][:2] == ["v1.0", "v1.1"]
    assert codes(judge_delivery(metrics, 28)) == {
        "delivery.high_failure_rate": "warning",
        "delivery.failed_deployments": "warning",
    }


def test_the_tiers_and_what_no_deployment_says() -> None:
    assert [frequency_tier(w) for w in (10, 7, 1, 0.25, 0.1)] == [
        "elite",
        "elite",
        "high",
        "medium",
        "low",
    ]
    assert [failure_tier(r) for r in (None, 0.0, 0.08, 0.15, 0.5)] == [
        "unknown",
        "elite",
        "high",
        "medium",
        "low",
    ]
    assert [recovery_tier(m) for m in (None, 30, 600, 3000, 20000)] == [
        "unknown",
        "elite",
        "high",
        "medium",
        "low",
    ]
    none = delivery_of([], [], of=None, environment=None, since=SINCE, now=NOW, days=28)
    assert (none.change_failure_rate, none.tiers.frequency) == (None, "low")
    assert codes(judge_delivery(none, 28)) == {"delivery.none": "info"}
    bad = delivery_of(
        [deployment("a", days_ago=20, incidents=1), deployment("b", days_ago=21, incidents=1)],
        [incident("x", minutes=3000)],
        of=None,
        environment=None,
        since=SINCE,
        now=NOW,
        days=28,
    )
    assert codes(judge_delivery(bad, 28)) == {
        "delivery.high_failure_rate": "critical",
        "delivery.slow_recovery": "warning",
        "delivery.stale": "info",
    }


# ── incident investigation ───────────────────────────────────────────────────


def test_one_severity_scale_whatever_the_tool_said() -> None:
    said = {
        ("SEV-1", None): "critical",
        ("P1", None): "critical",
        (None, "highest"): "critical",
        ("sev2", None): "high",
        (None, "major"): "high",
        ("P3", None): "medium",
        (None, "low"): "low",
        (None, None): "unknown",
        ("whatever", None): "unknown",
    }
    for (severity, priority), expected in said.items():
        assert severity_of(incident("x", severity=severity, priority=priority)) == expected


def test_an_incident_history_open_recurring_severe_slow() -> None:
    incidents = [
        incident("a", severity="sev1", minutes=300, causes=("v1.4.0",)),
        incident("b", severity="sev2", minutes=500, causes=("v1.4.0",)),
        incident("c", priority="high", state="open", minutes=None),
    ]
    history = history_of(incidents, of="Billing API", since=SINCE)
    assert (history.total, history.open) == (3, 1)
    assert history.by_severity == {"critical": 1, "high": 2}
    assert (history.mttr_minutes, history.longest_minutes) == (400, 500)
    assert [(r.cause, r.count) for r in history.recurring_causes] == [("v1.4.0", 2)]
    assert codes(judge_history(history, 30)) == {
        "incident.severe": "critical",
        "incident.open": "warning",
        "incident.recurring": "warning",
        "incident.slow_recovery": "warning",
    }
    quiet = history_of([], of="Checkout", since=SINCE)
    assert codes(judge_history(quiet, 30)) == {"incident.quiet": "info"}


# ── infrastructure ───────────────────────────────────────────────────────────


def test_an_inventory_and_what_stands_out() -> None:
    resources = [
        resource("i-api", criticality="critical"),
        resource("i-orphan", owned=False),
        resource("i-key", owned=False, criticality="high"),
        resource("lb-web", exposure="public", provider="aws"),
        resource("i-old", state="terminated"),
        resource("vm-1", state="failed", provider="azure"),
        resource("fn", state=None, provider="gcp"),
    ]
    inventory = inventory_of(resources, Citer())
    assert inventory.total == 7
    assert inventory.by_provider == {"aws": 5, "azure": 1, "gcp": 1}
    assert inventory.by_state == {"running": 4, "terminated": 1, "failed": 1, "unknown": 1}
    assert (inventory.public, inventory.unowned) == (1, 2)
    # The most critical first; what runs and is owned and quiet is left out.
    assert [r.name for r in inventory.notable] == [
        "i-api",
        "i-key",
        "i-old",
        "i-orphan",
        "lb-web",
        "vm-1",
    ]
    assert codes(judge_inventory(inventory)) == {
        "infra.unowned_critical": "critical",
        "infra.unowned": "warning",
        "infra.failed": "warning",
        "infra.not_running": "info",
        "infra.public": "info",
    }
    assert codes(judge_inventory(inventory_of([], Citer()))) == {"infra.empty": "info"}


# ── security ─────────────────────────────────────────────────────────────────


def test_a_security_posture_the_exposed_first() -> None:
    posture = SecurityPosture(
        public_resources=[
            Exposed(
                **named("lb-web", "infra_resource").model_dump(),
                kind="load_balancer",
                provider="aws",
                criticality="critical",
                owned=True,
            ),
            Exposed(
                **named("bucket", "infra_resource").model_dump(),
                kind="bucket",
                provider="aws",
                criticality=None,
                owned=False,
            ),
        ],
        public_repositories=[named("acme/billing-api", "repository")],
        sensitive_data=[
            Sensitive(
                **named("ledger", "database").model_dump(),
                classification="restricted",
                categories=["credential", "contact"],
                personal=True,
                owned=False,
            ),
        ],
    )
    said = judge_posture(posture)
    assert codes(said) == {
        "security.public_critical": "critical",
        "security.unowned_exposed": "critical",
        "security.public_resources": "warning",
        "security.public_repositories": "warning",
        "security.secrets_stored": "warning",
        "security.personal_data": "info",
    }
    assert said[1].params == {"resources": ["bucket"]}
    calm = SecurityPosture(public_resources=[], public_repositories=[], sensitive_data=[])
    assert codes(judge_posture(calm)) == {"security.nothing_exposed": "info"}


# ── data analysis ────────────────────────────────────────────────────────────


def test_a_data_landscape_secrets_personal_unowned_shared() -> None:
    def store(name: str, **fields: Any) -> Store:
        said: dict[str, Any] = {
            "engine": "postgresql",
            "schemas": 1,
            "objects": 3,
            "classification": None,
            "categories": [],
            "personal": False,
            "owners": ["Payments"],
            "services": [],
            **fields,
        }
        return Store(**named(name, "database").model_dump(), **said)

    landscape = DataLandscape(
        databases=[
            store("ledger", personal=True, categories=["contact"]),
            store("shop", owners=[], services=["a", "b", "c"]),
        ],
        sensitive_objects=[
            SensitiveObject(
                **named("billing.credentials", "data_object").model_dump(),
                database="ledger",
                classification="restricted",
                categories=["credential"],
            ),
        ],
    )
    assert codes(judge_data(landscape)) == {
        "data.secrets": "warning",
        "data.personal": "info",
        "data.unowned": "warning",
        "data.shared": "info",
    }
    assert codes(judge_data(DataLandscape(databases=[], sensitive_objects=[]))) == {
        "data.none": "info"
    }


# ── documentation ────────────────────────────────────────────────────────────


def test_documentation_coverage_gaps_and_freshness() -> None:
    def gap(name: str, criticality: str | None) -> Gap:
        return Gap(
            **named(name).model_dump(),
            criticality=criticality,
            owners=[],
            documents=0,
            last_documented_at=None,
        )

    said = DocumentationCoverageSaid(
        documents=4,
        spaces=1,
        freshness={"fresh": 1, "stale": 3},
        coverage=[
            KindCoverage(type="service", total=4, documented=1, fresh=1, percent=25),
            KindCoverage(type="application", total=2, documented=2, fresh=1, percent=100),
            KindCoverage(type="database", total=0, documented=0, fresh=0, percent=0),
        ],
        undocumented=[gap("payment-api", "critical"), gap("cron", None)],
        stale=[],
    )
    assert codes(judge_coverage(said)) == {
        "docs.critical_undocumented": "warning",
        "docs.low_coverage": "warning",
        "docs.gaps": "info",
        "docs.mostly_stale": "info",
    }
    nothing = DocumentationCoverageSaid(
        documents=0, spaces=0, freshness={}, coverage=[], undocumented=[], stale=[]
    )
    assert codes(judge_coverage(nothing)) == {"docs.none": "info"}


# ── architecture, testing, a change, a repository ────────────────────────────


def test_a_blast_radius_concentration_business_ownership() -> None:
    radius = BlastRadius(
        of="postgres-prod",
        type="database",
        criticality="critical",
        owners=[],
        direct=[named("a"), named("b"), named("c")],
        indirect=[],
        applications=[],
        business=[named("Invoicing", "business_capability")],
        depends_on=0,
    )
    assert codes(judge_radius(radius)) == {
        "architecture.concentration": "warning",
        "architecture.business_critical": "warning",
        "architecture.unowned_critical": "critical",
    }
    leaf = radius.model_copy(update={"direct": [], "business": [], "owners": ["Data"]})
    assert codes(judge_radius(leaf)) == {"architecture.leaf": "info"}


def test_a_test_scope_critical_fragile_business() -> None:
    def to_test(name: str, criticality: str | None, incidents: int) -> ToTest:
        return ToTest(
            **named(name).model_dump(), steps=1, criticality=criticality, incidents_30d=incidents
        )

    scope = ScopeToTest(
        of="Billing API",
        to_test=[to_test("Checkout", "high", 2), to_test("Mailer", None, 0)],
        total=2,
        applications=[],
        business=[named("Invoicing", "business_capability")],
    )
    assert codes(judge_scope(scope)) == {
        "test.critical_dependents": "warning",
        "test.fragile_dependents": "warning",
        "test.business_flows": "info",
    }
    alone = ScopeToTest(of="cron", to_test=[], total=0, applications=[], business=[])
    assert codes(judge_scope(alone)) == {"test.isolated": "info"}


def test_a_change_reviewed() -> None:
    review = ChangeReview(
        of="v1.4.0 to production",
        kind="deployment",
        at=NOW,
        state="failed",
        environment="production",
        by="sara",
        touches=[named("Billing API")],
        critical_targets=["Billing API"],
        reach=Reach(
            dependents=[named("Checkout")],
            applications=[],
            business=[named("Invoicing", "business_capability")],
        ),
        incidents_after=[
            IncidentSaid(
                id="event:x", name="Invoices fail", severity="high", opened_at=NOW, how="followed"
            )
        ],
    )
    assert codes(judge_change(review)) == {
        "change.followed_by_incident": "critical",
        "change.failed": "warning",
        "change.critical_target": "warning",
        "change.wide_reach": "warning",
        "change.production": "info",
    }
    quiet = review.model_copy(
        update={
            "state": "succeeded",
            "environment": "staging",
            "critical_targets": [],
            "reach": Reach(dependents=[], applications=[], business=[]),
            "incidents_after": [],
        }
    )
    assert judge_change(quiet) == []


def test_a_repository_profiled() -> None:
    profile = RepositoryProfile(
        of="acme/billing-api",
        languages=["Python"],
        visibility="public",
        default_branch="main",
        topics=[],
        archived=False,
        owners=[],
        maintainers=[],
        builds=[],
        activity=Activity(merges=0, releases=0, deployments=0, last_at=None),
        open_findings=2,
    )
    assert codes(judge_repository(profile, 30)) == {
        "repository.public": "warning",
        "repository.unowned": "warning",
        "repository.inactive": "info",
        "repository.open_findings": "info",
    }


# ── to an agent ──────────────────────────────────────────────────────────────


def _agent(**fields: Any) -> Definition:
    said: dict[str, Any] = {
        "key": "release-analysis",
        "title": "Release",
        "summary": "Releases, analysed.",
        "category": "development",
        "kind": Kind.AGENT,
        "version": "1.1.0",
        "lifecycle": Lifecycle.ACTIVE,
        **fields,
    }
    return Definition(**said)


def test_an_agent_is_offered_a_skill_only_within_what_it_reads() -> None:
    reads = ("deployment", "incident", "service", "application", "repository")
    given, kept = agent_skill_tools(
        _agent(entity_types=reads, skills=("delivery-metrics", "blast-radius", "nope", "find"))
    )
    assert [t.name for t in given] == ["delivery-metrics"]
    assert given[0].parameters["properties"]["days"]["maximum"] == 180
    assert [(k.tool, k.why) for k in kept] == [
        ("blast-radius", "out_of_scope"),
        ("nope", "unknown"),
        # LEKA's own reads read anything: never an agent's.
        ("find", "out_of_scope"),
    ]
    assert agent_skill_tools(_agent(entity_types=reads)) == ([], [])


# ── documented ───────────────────────────────────────────────────────────────


def test_every_skill_and_every_signal_is_documented() -> None:
    """docs/skills.md is the catalogue people read: a skill or a signal it
    does not name, nobody can rely on."""
    root = Path(__file__).resolve().parents[2]
    said = (root / "docs" / "skills.md").read_text(encoding="utf-8")
    source = (Path(library.__file__)).read_text(encoding="utf-8")
    signals = set(re.findall(r'"([a-z]+\.[a-z_]+)",\n\s+"(?:info|warning|critical)', source))
    signals |= set(re.findall(r'signal\(\s*"([a-z]+\.[a-z_]+)"', source))
    assert len(signals) >= 50
    missing = [f"`{c}`" for c in sorted({s.key for s in LIBRARY} | signals) if f"`{c}`" not in said]
    assert not missing, f"not in docs/skills.md: {missing}"
