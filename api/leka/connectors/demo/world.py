# ruff: noqa: E501 — records as their tools write them, one sentence a line.
"""Nova Retail: the company a demonstration reads (LEKA-449).

Fictive, and coherent the way a real company's tools are: an e-commerce
shop whose code lives in one GitHub repository, its work in Jira, its
monitoring in Datadog, its documentation in Confluence. Each tool says it
in its vendor's own words — the payloads its connector would have read —
so LEKA reads it with the stages it reads a customer's with.

What it holds, so a first question finds something:

    the code        nova-retail/nova: the storefront, checkout-api,
                    catalog-api, a worker, PostgreSQL, Redis, Amazon S3
    the teams       Paiements (Léa Martin, Tom Durand), Catalogue (Inès
                    Roux, Samir Benali), Plateforme (Samir Benali)
    a change        3-D Secure v2 on the checkout (#212), released in
                    v2.14.0, deployed to production yesterday morning
    what followed   refused payments up since: the Datadog monitor alerts,
                    incident #42 is open, NOVA-130 tracks it, its likely
                    cause NOVA-131 — Stripe timeouts no longer retried
    the documents   the architecture of the platform, checkout-api's
                    runbook, who owns what

Every date is said from now: what changed « this week » always has.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from leka.connectors.base import Capability
from leka.connectors.components import discover, layout
from leka.connectors.models import SourceKind
from leka.connectors.schemas import RawRecord

C = Capability
REPOSITORY = "nova-retail/nova"
REPO_URL = f"https://github.com/{REPOSITORY}"
JIRA_SITE = "nova-retail.atlassian.net"
WIKI = "https://nova-retail.atlassian.net/wiki"
DATADOG = "https://app.datadoghq.eu"

# The sources a demonstration has: kind, name, configuration, credentials —
# never sent anywhere (a replayed source reaches nothing), only stored as a
# source's are.
FAKE = "demonstration-nova-retail"
SOURCES: tuple[tuple[SourceKind, str, dict[str, object], dict[str, str]], ...] = (
    (SourceKind.GITHUB, "GitHub Nova", {"organization": "nova-retail"}, {"token": FAKE}),
    (
        SourceKind.JIRA,
        "Jira Nova",
        {"site": JIRA_SITE},
        {"token": FAKE, "email": "demo@nova-retail.example"},
    ),
    (
        SourceKind.DATADOG,
        "Datadog Nova",
        {"site": "datadoghq.eu"},
        {"application_key": FAKE, "api_key": FAKE},
    ),
    (
        SourceKind.CONFLUENCE,
        "Confluence Nova",
        {"site": JIRA_SITE},
        {"token": FAKE, "email": "demo@nova-retail.example"},
    ),
)

# Who works there, as each tool knows them.
PEOPLE = {
    "lea": ("lea-martin", "acc-lea", "Léa Martin", "lea.martin@nova-retail.example"),
    "tom": ("tom-durand", "acc-tom", "Tom Durand", "tom.durand@nova-retail.example"),
    "ines": ("ines-roux", "acc-ines", "Inès Roux", "ines.roux@nova-retail.example"),
    "samir": ("samir-benali", "acc-samir", "Samir Benali", "samir.benali@nova-retail.example"),
}

# ── the code ─────────────────────────────────────────────────────────────────

COMPOSE = """\
name: nova
x-backend: &backend
  env_file: [production.env]
  environment:
    NOVA_REDIS_URL: redis://redis:6379/0
services:
  checkout-api:
    <<: *backend
    image: ghcr.io/nova-retail/checkout-api:${NOVA_RELEASE}
    expose: ["8000"]
    depends_on: [redis, catalog-api]
  catalog-api:
    <<: *backend
    image: ghcr.io/nova-retail/catalog-api:${NOVA_RELEASE}
    expose: ["8001"]
    depends_on: [redis]
  worker:
    <<: *backend
    image: ghcr.io/nova-retail/checkout-api:${NOVA_RELEASE}
    command: ["python", "-m", "nova.worker"]
    depends_on: [redis]
  storefront:
    image: ghcr.io/nova-retail/storefront:${NOVA_RELEASE}
    expose: ["3000"]
    depends_on: [checkout-api, catalog-api]
  redis:
    image: redis:7-alpine
"""

ENV = """\
NOVA_APP_DOMAIN=shop.nova-retail.example

# ── the database: Amazon RDS for PostgreSQL, eu-west-3 ──
# postgresql+asyncpg://nova:<password>@<endpoint>:5432/nova?ssl=require
NOVA_DATABASE_URL=

# ── product images: Amazon S3, eu-west-3 ──
NOVA_OBJECT_STORE=s3
NOVA_S3_BUCKET=
NOVA_S3_REGION=eu-west-3
"""

PYPROJECT = """\
[project]
name = "nova-checkout"
dependencies = ["fastapi>=0.115.0", "sqlalchemy[asyncio]>=2.0", "asyncpg>=0.30", "redis>=5.2", "rq>=2.0", "stripe>=11.0"]
"""

PACKAGE = """\
{"dependencies": {"next": "15.5.0", "react": "19.1.0"}, "devDependencies": {"typescript": "5"}}
"""

FILES = {
    "deploy/docker-compose.production.yml": COMPOSE,
    "deploy/production.env.example": ENV,
    "checkout-api/pyproject.toml": PYPROJECT,
    "checkout-api/Dockerfile": "FROM python:3.12-slim\n",
    "catalog-api/go.mod": "module github.com/nova-retail/nova/catalog-api\n\ngo 1.23\n",
    "catalog-api/Dockerfile": "FROM golang:1.23-alpine\n",
    "storefront/package.json": PACKAGE,
    "storefront/Dockerfile": "FROM node:22-alpine\n",
}
TREE = [
    *FILES,
    "checkout-api/nova/payments/stripe.py",
    "checkout-api/nova/payments/three_ds.py",
    "checkout-api/nova/worker.py",
    "checkout-api/tests/test_payments.py",
    "catalog-api/prices/cache.go",
    "storefront/app/checkout/page.tsx",
    "docs/architecture.md",
]


def records(kind: SourceKind, now: datetime) -> dict[Capability, list[RawRecord]]:
    """What a source of this kind holds at Nova Retail, said as of now."""
    said = {
        SourceKind.GITHUB: _github,
        SourceKind.JIRA: _jira,
        SourceKind.DATADOG: _datadog,
        SourceKind.CONFLUENCE: _confluence,
    }.get(kind)
    if said is None:
        return {}
    found: dict[Capability, list[RawRecord]] = {}
    for capability, external_id, container, payload in said(_Clock(now)):
        found.setdefault(capability, []).append(
            RawRecord(
                kind=capability,
                external_id=external_id,
                container=container,
                payload=payload,
                fetched_at=now,
            )
        )
    return found


class _Clock:
    """Dates said from now, as the tools write them."""

    def __init__(self, now: datetime) -> None:
        self.now = now.astimezone(UTC).replace(microsecond=0)

    def ago(self, *, days: float = 0, hours: float = 0) -> str:
        return (self.now - timedelta(days=days, hours=hours)).isoformat().replace("+00:00", "Z")


Said = list[tuple[Capability, str, str | None, dict[str, Any]]]


def _github(at: _Clock) -> Said:
    out: Said = [
        (
            C.REPOSITORIES,
            "R_nova",
            None,
            {
                "node_id": "R_nova",
                "full_name": REPOSITORY,
                "description": "La plateforme e-commerce de Nova Retail : boutique, paiement, catalogue.",
                "language": "Python",
                "topics": ["e-commerce", "payments"],
                "private": True,
                "default_branch": "main",
                "html_url": REPO_URL,
                "owner": {"login": "nova-retail"},
            },
        ),
    ]
    for slug, name, lead, members in (
        ("paiements", "Paiements", "lea", ["lea", "tom"]),
        ("catalogue", "Catalogue", "ines", ["ines", "samir"]),
        ("plateforme", "Plateforme", "samir", ["samir"]),
    ):
        out.append(
            (
                C.TEAMS,
                f"T_{slug}",
                None,
                {
                    "slug": slug,
                    "name": name,
                    "html_url": f"https://github.com/orgs/nova-retail/teams/{slug}",
                    "description": f"L'équipe {name} de Nova Retail.",
                    "privacy": "closed",
                    "maintainers": [PEOPLE[lead][0]],
                    "members": [PEOPLE[m][0] for m in members],
                },
            )
        )
    for sha, who, message, days in (
        ("a1f3", "tom", "feat(checkout): 3-D Secure v2 on card payments", 3),
        ("b7c2", "tom", "fix(checkout): drop the Stripe retry wrapper, 3DS handles it", 2.5),
        ("c9d4", "lea", "chore(release): v2.14.0", 1.2),
        ("d2e8", "ines", "feat(catalog): cache prices in Redis for 60 s", 6),
        ("e5a1", "samir", "build(deploy): Redis 7 on production", 8),
    ):
        login, _, name, email = PEOPLE[who]
        out.append(
            (
                C.COMMITS,
                f"C_{sha}",
                REPOSITORY,
                {
                    "node_id": f"C_{sha}",
                    "sha": sha,
                    "html_url": f"{REPO_URL}/commit/{sha}",
                    "commit": {
                        "message": message,
                        "author": {"name": name, "email": email, "date": at.ago(days=days)},
                        "committer": {"name": name, "email": email, "date": at.ago(days=days)},
                    },
                    "author": {"login": login},
                    "parents": [{"sha": "0"}],
                },
            )
        )
    for number, title, body, who, labels, opened, merged, branch in (
        (
            212,
            "3-D Secure v2 sur le paiement par carte",
            "NOVA-128. Le paiement passe par 3-D Secure v2 ; le wrapper de relance Stripe est retiré.",
            "tom",
            ["feature", "payments"],
            4,
            2.4,
            "feat/NOVA-128-3ds-v2",
        ),
        (
            209,
            "Cache des prix du catalogue dans Redis",
            "NOVA-125.",
            "ines",
            ["feature"],
            7,
            6,
            "feat/NOVA-125-price-cache",
        ),
        (
            215,
            "Relancer les timeouts Stripe",
            "Fixes #214. NOVA-131 : remet la relance sur les timeouts Stripe, retirée par #212.",
            "lea",
            ["bug", "payments"],
            0.3,
            None,
            "fix/NOVA-131-stripe-retry",
        ),
    ):
        out.append(
            (
                C.PULL_REQUESTS,
                f"PR_{number}",
                REPOSITORY,
                {
                    "node_id": f"PR_{number}",
                    "number": number,
                    "title": title,
                    "body": body,
                    "state": "closed" if merged is not None else "open",
                    "draft": False,
                    "merged_at": at.ago(days=merged) if merged is not None else None,
                    "closed_at": at.ago(days=merged) if merged is not None else None,
                    "created_at": at.ago(days=opened),
                    "updated_at": at.ago(days=merged if merged is not None else 0.1),
                    "html_url": f"{REPO_URL}/pull/{number}",
                    "user": {"login": PEOPLE[who][0]},
                    "assignees": [{"login": PEOPLE[who][0]}],
                    "requested_reviewers": [{"login": PEOPLE["lea" if who != "lea" else "tom"][0]}],
                    "labels": [{"name": n} for n in labels],
                    "head": {"ref": branch},
                    "base": {"ref": "main"},
                },
            )
        )
    out.append(
        (
            C.ISSUES,
            "I_214",
            REPOSITORY,
            {
                "node_id": "I_214",
                "number": 214,
                "title": "Paiements refusés en hausse depuis la v2.14.0",
                "body": "Depuis le déploiement d'hier, des paiements par carte échouent sur un timeout Stripe.",
                "state": "open",
                "labels": [{"name": "bug"}, {"name": "incident"}],
                "user": {"login": PEOPLE["lea"][0]},
                "html_url": f"{REPO_URL}/issues/214",
                "created_at": at.ago(hours=20),
                "updated_at": at.ago(hours=2),
            },
        )
    )
    for tag, days, notes in (
        ("v2.14.0", 1.2, "- 3-D Secure v2 sur le paiement par carte (#212)"),
        ("v2.13.2", 8, "- Cache des prix du catalogue (#209)\n- Redis 7"),
    ):
        out.append(
            (
                C.RELEASES,
                f"RE_{tag}",
                REPOSITORY,
                {
                    "tag_name": tag,
                    "name": tag,
                    "html_url": f"{REPO_URL}/releases/tag/{tag}",
                    "draft": False,
                    "prerelease": False,
                    "created_at": at.ago(days=days),
                    "published_at": at.ago(days=days),
                    "body": notes,
                    "author": {"login": PEOPLE["lea"][0]},
                },
            )
        )
    for number, ref, environment, days in (
        (88, "v2.14.0", "production", 1),
        (87, "v2.14.0", "staging", 1.3),
        (84, "v2.13.2", "production", 8),
    ):
        out.append(
            (
                C.DEPLOYMENTS,
                f"DE_{number}",
                REPOSITORY,
                {
                    "url": f"https://api.github.com/repos/{REPOSITORY}/deployments/{number}",
                    "id": number,
                    "node_id": f"DE_{number}",
                    "sha": "c9d4",
                    "ref": ref,
                    "environment": environment,
                    "production_environment": environment == "production",
                    "creator": {"login": PEOPLE["lea"][0]},
                    "created_at": at.ago(days=days),
                    "updated_at": at.ago(days=days, hours=-0.2),
                    "statuses": [
                        {"state": "success", "created_at": at.ago(days=days, hours=-0.2)},
                        {"state": "in_progress", "created_at": at.ago(days=days)},
                    ],
                },
            )
        )
    found = discover(REPOSITORY, FILES)
    out.append(
        (
            C.COMPONENTS,
            "R_nova:_layout",
            REPOSITORY,
            {
                "name": "_layout",
                "kind": "layout",
                "display_name": REPOSITORY,
                "repository": REPOSITORY,
                "repository_url": REPO_URL,
                "default_branch": "main",
                **layout(TREE, found),
            },
        )
    )
    for component in found:
        out.append(
            (
                C.COMPONENTS,
                f"R_nova:{component['name']}",
                REPOSITORY,
                {**component, "repository_url": REPO_URL, "default_branch": "main"},
            )
        )
    return out


def _person(who: str) -> dict[str, str]:
    _, account, name, email = PEOPLE[who]
    return {"accountId": account, "displayName": name, "emailAddress": email}


def _adf(text: str) -> dict[str, object]:
    """Atlassian Document Format, one paragraph."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _jira(at: _Clock) -> Said:
    out: Said = [
        (
            C.PROJECTS,
            "10001",
            "NOVA",
            {
                "id": "10001",
                "key": "NOVA",
                "name": "Nova Retail",
                "self": f"https://{JIRA_SITE}/rest/api/3/project/10001",
                "projectTypeKey": "software",
                "description": "Le travail des équipes produit et technique de Nova Retail.",
                "lead": _person("lea"),
            },
        )
    ]
    for key, kind, summary, text, status, category, who, days, links, labels in (
        (
            "NOVA-130",
            "Incident",
            "Hausse des paiements refusés sur checkout-api",
            "Depuis le déploiement de la v2.14.0, 6 % des paiements par carte échouent "
            "(contre 0,8 % d'habitude). Suivi de l'incident Datadog #42.",
            ("En cours", "indeterminate"),
            None,
            "lea",
            0.8,
            [("Causes", "inwardIssue", "NOVA-131")],
            ["incident", "paiement"],
        ),
        (
            "NOVA-131",
            "Bug",
            "Les timeouts Stripe ne sont plus relancés",
            "La PR #212 a retiré le wrapper de relance : un timeout Stripe fait échouer le paiement.",
            ("À faire", "new"),
            None,
            "tom",
            0.6,
            [],
            ["paiement"],
        ),
        (
            "NOVA-128",
            "Story",
            "3-D Secure v2 sur le paiement par carte",
            "Obligation DSP2 : passer le paiement par carte en 3-D Secure v2.",
            ("Terminé", "done"),
            "Done",
            "tom",
            9,
            [],
            ["paiement", "conformité"],
        ),
        (
            "NOVA-125",
            "Task",
            "Mettre en cache les prix du catalogue",
            "Les pages produit lisent les prix à chaque affichage : un cache Redis de 60 s.",
            ("Terminé", "done"),
            "Done",
            "ines",
            10,
            [],
            ["performance"],
        ),
        (
            "NOVA-133",
            "Story",
            "Migrer les images produit d'Amazon S3 vers le CDN",
            "Préparer la migration : dépendances, risques, ordre des étapes, retour arrière.",
            ("À faire", "new"),
            None,
            "samir",
            2,
            [],
            ["migration"],
        ),
    ):
        status_name, status_category = status
        fields: dict[str, Any] = {
            "summary": summary,
            "description": _adf(text),
            "issuetype": {"name": kind},
            "status": {"name": status_name, "statusCategory": {"key": status_category}},
            "priority": {"name": "High" if kind in ("Incident", "Bug") else "Medium"},
            "labels": labels,
            "components": [{"name": "nova-checkout-api" if "paiement" in labels else "nova-catalog-api"}],
            "created": at.ago(days=days),
            "updated": at.ago(days=min(days, 0.2)),
            "assignee": _person(who),
            "reporter": _person("lea"),
            "creator": _person("lea"),
            "project": {"key": "NOVA", "name": "Nova Retail"},
            "issuelinks": [
                {
                    "type": {"name": name, "inward": "is caused by", "outward": "causes"},
                    side: {"key": other},
                }
                for name, side, other in links
            ],
        }
        if category:
            fields["resolution"] = {"name": category}
            fields["resolutiondate"] = at.ago(days=days - 1)
        out.append(
            (
                C.ISSUES,
                key,
                "NOVA",
                {
                    "id": key,
                    "key": key,
                    "self": f"https://{JIRA_SITE}/rest/api/3/issue/{key}",
                    "fields": fields,
                },
            )
        )
    return out


def _datadog(at: _Clock) -> Said:
    out: Said = []
    for number, name, state, query, service, team, priority in (
        (
            301,
            "nova-checkout-api — taux de paiements refusés",
            "Alert",
            "sum(last_15m):sum:nova.payments.refused{env:production}.as_count() > 50",
            "nova-checkout-api",
            "paiements",
            1,
        ),
        (
            302,
            "nova-checkout-api — latence p99",
            "Warn",
            "avg(last_5m):p99:trace.http.request{service:nova-checkout-api} > 1.5",
            "nova-checkout-api",
            "paiements",
            2,
        ),
        (
            303,
            "nova-catalog-api — erreurs 5xx",
            "OK",
            "sum(last_5m):sum:trace.http.request.errors{service:nova-catalog-api}.as_count() > 20",
            "nova-catalog-api",
            "catalogue",
            3,
        ),
    ):
        out.append(
            (
                C.ALERTS,
                str(number),
                service,
                {
                    "id": number,
                    "name": name,
                    "type": "query alert",
                    "query": query,
                    "message": f"@slack-{team} Voir le runbook de {service}.",
                    "tags": [f"service:{service}", "env:production", f"team:{team}"],
                    "overall_state": state,
                    "created": at.ago(days=120),
                    "modified": at.ago(hours=19) if state != "OK" else at.ago(days=30),
                    "priority": priority,
                    "web_url": f"{DATADOG}/monitors/{number}",
                },
            )
        )
    out.append(
        (
            C.INCIDENTS,
            "00000000-0000-0000-0000-000000000042",
            None,
            {
                "id": "00000000-0000-0000-0000-000000000042",
                "type": "incidents",
                "attributes": {
                    "public_id": 42,
                    "title": "Paiements refusés en hausse",
                    "state": "active",
                    "severity": "SEV-2",
                    "customer_impacted": True,
                    "customer_impact_scope": "6 % des paiements par carte échouent sur la boutique.",
                    "created": at.ago(hours=19),
                    "modified": at.ago(hours=1),
                    "fields": {"services": {"type": "autocomplete", "value": ["nova-checkout-api"]}},
                },
                "people": {
                    "commander_user": {"name": PEOPLE["lea"][2], "email": PEOPLE["lea"][3]},
                    "created_by_user": {"name": PEOPLE["tom"][2], "email": PEOPLE["tom"][3]},
                },
                "web_url": f"{DATADOG}/incidents/42",
            },
        )
    )
    out.append(
        (
            C.EVENTS,
            "AQAAAYnova88",
            None,
            {
                "id": "AQAAAYnova88",
                "type": "event",
                "attributes": {
                    "timestamp": at.ago(days=1),
                    "message": "Deploy v2.14.0 of nova-checkout-api to production",
                    "tags": ["service:nova-checkout-api", "env:production", "deployment"],
                    "attributes": {
                        "title": "Deploy v2.14.0",
                        "service": "nova-checkout-api",
                        "status": "info",
                    },
                },
            },
        )
    )
    for service, team, display, kind, languages, depends, tier in (
        ("nova-checkout-api", "paiements", "Nova Checkout API", "web", ["python"], ["nova-catalog-api"], "1"),
        ("nova-catalog-api", "catalogue", "Nova Catalog API", "web", ["go"], [], "2"),
        (
            "nova-storefront",
            "plateforme",
            "Storefront",
            "web",
            ["typescript"],
            ["nova-checkout-api", "nova-catalog-api"],
            "1",
        ),
    ):
        out.append(
            (
                C.SERVICES,
                service,
                None,
                {
                    "id": service,
                    "type": "service-definition",
                    "attributes": {
                        "schema": {
                            "apiVersion": "v3",
                            "kind": "service",
                            "metadata": {
                                "name": service,
                                "displayName": display,
                                "owner": team,
                                "description": f"{display}, de l'application Nova Commerce.",
                                "links": [
                                    {"type": "runbook", "url": f"{WIKI}/spaces/ENG/pages/2002"},
                                    {"type": "repo", "url": REPO_URL},
                                ],
                            },
                            "spec": {
                                "tier": tier,
                                "lifecycle": "production",
                                "type": kind,
                                "languages": languages,
                                "dependsOn": [f"service:{d}" for d in depends],
                                "componentOf": ["system:nova-commerce"],
                            },
                        },
                        "meta": {"last-modified-time": at.ago(days=40)},
                    },
                },
            )
        )
    return out


def _confluence(at: _Clock) -> Said:
    out: Said = [
        (
            C.SPACES,
            "1001",
            None,
            {
                "id": "1001",
                "key": "ENG",
                "name": "Ingénierie Nova",
                "type": "global",
                "status": "current",
                "web_url": f"{WIKI}/spaces/ENG",
                "description": {"plain": {"value": "Architecture, runbooks et équipes."}},
            },
        )
    ]
    for page, title, owner, days, body in (
        (
            "2001",
            "Architecture de la plateforme Nova",
            "samir",
            20,
            "<p>La boutique <strong>storefront</strong> (Next.js) appelle <strong>checkout-api</strong> "
            "(Python, FastAPI) pour le paiement et <strong>catalog-api</strong> (Go) pour les produits "
            "et les prix.</p><p>checkout-api passe les paiements par Stripe, garde les commandes dans "
            "PostgreSQL (Amazon RDS, eu-west-3) et met ses tâches en file dans Redis, que lit le "
            "worker. Les images produit sont dans Amazon S3.</p>",
        ),
        (
            "2002",
            "Runbook — checkout-api",
            "lea",
            15,
            "<p>Responsable : équipe Paiements (Léa Martin). En cas de hausse des paiements refusés : "
            "vérifier le moniteur Datadog, les timeouts Stripe et le dernier déploiement ; revenir à "
            "la version précédente si la hausse suit un déploiement.</p>",
        ),
        (
            "2003",
            "Équipes et responsabilités",
            "lea",
            30,
            "<p>Paiements (Léa Martin, Tom Durand) : checkout-api et le worker. Catalogue (Inès Roux, "
            "Samir Benali) : catalog-api. Plateforme (Samir Benali) : storefront, déploiement, "
            "infrastructure AWS.</p>",
        ),
    ):
        account = PEOPLE[owner][1]
        out.append(
            (
                C.PAGES,
                page,
                "ENG",
                {
                    "id": page,
                    "title": title,
                    "status": "current",
                    "spaceId": "1001",
                    "authorId": account,
                    "ownerId": account,
                    "createdAt": at.ago(days=days),
                    "version": {
                        "number": 3,
                        "createdAt": at.ago(days=days / 2),
                        "authorId": account,
                    },
                    "body": {"storage": {"value": body, "representation": "storage"}},
                    "web_url": f"{WIKI}/spaces/ENG/pages/{page}",
                },
            )
        )
    return out
