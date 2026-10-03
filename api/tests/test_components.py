"""What a repository's code says it runs (LEKA-369): leka.connectors.components.

The repository is LEKA's own, as it is deployed: a production compose file
with anchors — an API image run four ways, a web app, Redis, Caddy — its
env example, its Caddyfile, its CD workflow, its manifests; and a
development compose beside it, full of test databases.

What these protect: every service of the code found, with its language and
framework, where it is reached, what deploys it; each store and service
outside it relies on, from configuration only — the drivers it carries for
its customers' databases are not its databases, an empty setting is off,
the development compose's databases are not what runs; each link named,
with the file and line that say so; the files read, a few, none in a
dependency or a test. And what the repository is made of, from its tree:
each top-level folder a module — the code of a service, its docs, its
infrastructure, its CI, its agents — its files and languages, the parts of
a service's code; nothing installed or built.
"""

from __future__ import annotations

from typing import Any

import pytest

from leka.connectors.components import MAX_FILES, discover, layout, wanted

REPOSITORY = "Haitam-elh/Leka"

COMPOSE = """\
name: leka
x-logging: &logging
  logging:
    driver: json-file
x-backend: &backend
  image: ${LEKA_REGISTRY:?set LEKA_REGISTRY}/api:${LEKA_RELEASE:?set LEKA_RELEASE}
  env_file: [production.env]
  environment:
    LEKA_ENVIRONMENT: production
    LEKA_REDIS_URL: redis://redis:6379/0
x-app: &app
  <<: [*backend, *logging]
  restart: unless-stopped
  depends_on:
    redis:
      condition: service_healthy
    migrate:
      condition: service_completed_successfully
services:
  migrate:
    <<: [*backend, *logging]
    command: ["python", "-m", "leka.db.migrate"]
    restart: "no"
  api:
    <<: *app
    expose: ["8000"]
  worker:
    <<: *app
    command: ["python", "-m", "leka.platform.worker"]
  scheduler:
    <<: *app
    command: ["python", "-m", "leka.platform.scheduler"]
  web:
    <<: *logging
    image: ${LEKA_REGISTRY}/web:${LEKA_RELEASE}
    expose: ["3000"]
  redis:
    image: redis:7-alpine
  caddy:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    environment:
      LEKA_APP_DOMAIN: ${LEKA_APP_DOMAIN:?set LEKA_APP_DOMAIN}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
    depends_on: [api, web]
"""

ENV = """\
# Every name must point at this box in DNS.
LEKA_APP_DOMAIN=leka-core.com
LEKA_API_DOMAIN=api.leka-core.com

# ── the database: Amazon RDS for PostgreSQL, eu-central-1 ──
# postgresql+asyncpg://leka:<password>@<endpoint>:5432/leka?ssl=require
LEKA_DATABASE_URL=

# ── object storage: Amazon S3, eu-central-1 ──
LEKA_OBJECT_STORE=s3
LEKA_S3_BUCKET=
LEKA_S3_REGION=eu-central-1

# ── e-mail: the OVH mailbox ──
LEKA_SMTP_HOST=ssl0.ovh.net
LEKA_SMTP_PASSWORD=

# ── monitoring ── Empty means off.
LEKA_SENTRY_DSN=
"""

CADDYFILE = """\
(common) {
\tencode zstd gzip
}

{$LEKA_APP_DOMAIN} {$LEKA_APP_ALIASES} {
\timport common
\treverse_proxy web:3000 {
\t\thealth_uri /login
\t}
}

{$LEKA_API_DOMAIN} {
\timport common
\treverse_proxy api:8000
}
"""

CD = """\
name: CD
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v6
        with:
          context: api
          tags: ${{ steps.what.outputs.registry }}/api:${{ steps.what.outputs.release }}
      - uses: docker/build-push-action@v6
        with:
          context: web
          build-args: |
            NEXT_PUBLIC_API_URL=${{ vars.PROD_API_URL }}
          tags: ${{ steps.what.outputs.registry }}/web:${{ steps.what.outputs.release }}
  deploy:
    environment: production
    steps:
      - uses: appleboy/scp-action@v0.1.7
        with:
          source: deploy/docker-compose.production.yml,deploy/Caddyfile
"""

PYPROJECT = """\
[project]
name = "leka"
dependencies = [
    "fastapi>=0.115.0",
    "sqlalchemy[asyncio]>=2.0.35,<2.1",
    "asyncpg>=0.30.0",
    "pymongo>=4.18,<5",
    "pymssql>=2.4.2,<3",
    "oracledb>=26.0.1,<27",
    "redis>=5.2.0",
    "rq>=2.0.0",
]
"""

PACKAGE = """\
{
  "dependencies": {"next": "15.5.25", "react": "19.1.0"},
  "devDependencies": {"typescript": "5"}
}
"""

DEV_COMPOSE = """\
services:
  postgres:
    image: pgvector/pgvector:pg16
  mysql:
    image: mysql:8.4
  oracle:
    image: gvenzl/oracle-free:23-slim-faststart
"""

FILES = {
    "deploy/docker-compose.production.yml": COMPOSE,
    "deploy/production.env.example": ENV,
    "deploy/Caddyfile": CADDYFILE,
    ".github/workflows/cd.yml": CD,
    "api/pyproject.toml": PYPROJECT,
    "api/Dockerfile": "FROM python:3.12-slim\n",
    "web/package.json": PACKAGE,
    "web/Dockerfile": "FROM node:22-alpine\n",
    "docker-compose.yml": DEV_COMPOSE,
}


@pytest.fixture
def found() -> dict[str, dict[str, Any]]:
    return {str(c["name"]): c for c in discover(REPOSITORY, FILES)}


def links(component: dict[str, Any]) -> dict[str, str]:
    return {link["to"]: link["role"] for link in component["links"]}


def test_every_service_of_the_code_with_what_it_is_written_in(
    found: dict[str, dict[str, Any]],
) -> None:
    services = {
        n: (c["display_name"], c["role"]) for n, c in found.items() if c["kind"] == "service"
    }
    assert services == {
        "api": ("Leka API", "api"),
        "web": ("Leka Web", "web"),
        "worker": ("Leka Worker", "worker"),
        "scheduler": ("Leka Scheduler", "scheduler"),
        "migrate": ("Leka Migrate", "job"),
        "caddy": ("Leka Caddy", "proxy"),
    }
    assert found["api"]["technology"] == ["Python", "FastAPI"]
    assert found["api"]["code_path"] == "api"
    assert found["web"]["technology"] == ["TypeScript", "Next.js", "React"]
    # A worker is written with its queue, not with the API's web framework.
    assert found["worker"]["technology"] == ["Python", "RQ"]
    assert found["caddy"]["technology"] == ["Caddy"]


def test_where_each_is_reached_and_what_deploys_it(found: dict[str, dict[str, Any]]) -> None:
    assert found["web"]["public_url"] == "https://leka-core.com"
    assert found["api"]["public_url"] == "https://api.leka-core.com"
    for name in ("api", "web", "worker", "redis", "caddy"):
        assert found[name]["environment"] == "production"
        assert (found[name]["deployed_by"], found[name]["deploy_method"]) == (
            ".github/workflows/cd.yml",
            "ssh",
        )


def test_stores_and_services_outside_from_configuration_only(
    found: dict[str, dict[str, Any]],
) -> None:
    stores = {
        n: (c["kind"], c["engine"], c["role"]) for n, c in found.items() if c["kind"] != "service"
    }
    assert stores == {
        "redis": ("database", "redis", "cache"),
        # Its URL's example, in the comment above an empty value.
        "postgresql": ("database", "postgresql", "database"),
        "s3": ("storage", None, "storage"),
        "ovh-mail": ("external", None, "email"),
    }
    assert (found["s3"]["provider"], found["s3"]["region"]) == ("aws", "eu-central-1")
    assert found["ovh-mail"]["vendor"] == "OVH"
    # pymongo, pymssql, oracledb read the customers' databases: not LEKA's.
    # The development compose's databases are not what runs. An empty
    # Sentry DSN is off.
    assert not {"mongodb", "sqlserver", "oracle", "mysql", "postgres", "sentry"} & set(found)


def test_each_link_named_with_the_file_and_line_that_say_so(
    found: dict[str, dict[str, Any]],
) -> None:
    assert links(found["caddy"]) == {"api": "routes", "web": "routes"}
    assert links(found["web"]) == {"api": "calls"}
    # The API queues jobs (RQ): Redis is its queue, not a cache.
    assert links(found["api"]) == {
        "redis": "queue",
        "postgresql": "stores",
        "s3": "files",
        "ovh-mail": "email",
    }
    # Waiting for the migration to start is no dependency of what runs.
    assert "migrate" not in links(found["api"])
    evidence = {link["to"]: link["evidence"] for link in found["api"]["links"]}
    assert evidence["postgresql"] == "deploy/production.env.example:7 — LEKA_DATABASE_URL"
    assert evidence["redis"].endswith("LEKA_REDIS_URL")
    routes = {link["to"]: link["evidence"] for link in found["caddy"]["links"]}
    assert routes["api"] == "deploy/Caddyfile:14 — api"
    # And the link says what it reaches, for whoever reads it alone.
    reached = next(link for link in found["api"]["links"] if link["to"] == "ovh-mail")
    assert (reached["kind"], reached["display_name"], reached["vendor"]) == (
        "external",
        "OVH (e-mail)",
        "OVH",
    )


def test_without_a_production_compose_the_plain_one_is_read() -> None:
    found = {
        str(c["name"]): c
        for c in discover(
            "acme/shop",
            {
                "docker-compose.yml": """
services:
  app:
    build: .
    environment:
      - DATABASE_URL=postgres://shop@db:5432/shop
    depends_on: [db]
  db:
    image: postgres:16
""",
                "requirements.txt": "django==5.0\npsycopg[binary]\n",
            },
        )
    }

    assert found["app"]["display_name"] == "Shop App"
    assert found["app"]["technology"] == ["Python", "Django"]
    assert found["app"]["role"] == "api"
    assert links(found["app"]) == {"db": "stores"}
    assert (found["db"]["kind"], found["db"]["engine"], found["db"]["environment"]) == (
        "database",
        "postgresql",
        None,
    )


def test_an_nginx_proxy_and_a_configured_service_outside() -> None:
    found = {
        str(c["name"]): c
        for c in discover(
            "acme/pay",
            {
                "compose.prod.yaml": """
services:
  gateway:
    image: nginx:1.27
  billing:
    build: ./billing
    environment:
      STRIPE_SECRET_KEY: sk_live_from_the_vault
      SENTRY_DSN: ""
""",
                "nginx.conf": "location / { proxy_pass http://billing:8080; }\n",
                "billing/go.mod": (
                    "module acme/billing\n\nrequire github.com/gin-gonic/gin v1.10.0\n"
                ),
            },
        )
    }

    assert links(found["gateway"]) == {"billing": "routes"}
    assert found["billing"]["technology"] == ["Go", "Gin"]
    assert links(found["billing"]) == {"stripe": "uses"}
    assert found["stripe"]["role"] == "payments"
    assert "sentry" not in found


def test_a_tree_read_for_the_few_files_that_say_what_runs() -> None:
    tree = [
        "README.md",
        "api/leka/main.py",
        "api/pyproject.toml",
        "api/tests/oracle/docker-compose.yml",
        "web/node_modules/next/package.json",
        "web/package.json",
        "deploy/docker-compose.production.yml",
        "deploy/production.env.example",
        "deploy/Caddyfile",
        ".github/workflows/cd.yml",
        *(f"svc{n}/Dockerfile" for n in range(60)),
    ]

    chosen = wanted(tree)

    assert chosen[:4] == [
        ".github/workflows/cd.yml",
        "deploy/Caddyfile",
        "deploy/docker-compose.production.yml",
        "deploy/production.env.example",
    ]
    assert "api/pyproject.toml" in chosen and "web/package.json" in chosen
    assert not [p for p in chosen if "node_modules" in p or "/tests/" in p or p.endswith(".py")]
    assert len(chosen) == MAX_FILES


def test_a_file_that_is_not_yaml_is_read_as_nothing() -> None:
    assert discover("acme/broken", {"docker-compose.yml": "services: [unclosed"}) == []


TREE = [
    *FILES,
    "README.md",
    "api/leka/__init__.py",
    "api/leka/connectors/__init__.py",
    "api/leka/connectors/aws/connector.py",
    "api/leka/connectors/github/connector.py",
    "api/leka/connectors/github/__init__.py",
    "api/leka/ingestion/engine.py",
    "api/tests/__init__.py",
    "api/tests/test_api.py",
    "api/alembic/env.py",
    "web/app/page.tsx",
    "web/components/shell/sidebar.tsx",
    "web/node_modules/next/package.json",
    "docs/setup.md",
    "docs/adr/001-postgresql.md",
    "agents/registry.yaml",
    "agents/incident/correlate/SKILL.md",
    "agents/_template/SKILL.md",
    "node_modules/left-pad/index.js",
    ".vscode/settings.json",
]


def test_a_repository_is_its_modules_each_with_its_role_files_and_languages() -> None:
    laid = layout(TREE, discover(REPOSITORY, FILES))

    found = laid["modules"]
    assert isinstance(found, list)
    modules = {str(m["path"]): m for m in found}
    roles = {path: m["role"] for path, m in modules.items()}
    assert roles == {
        "api": "service",
        "web": "service",
        "docs": "docs",
        "deploy": "infrastructure",
        ".github": "ci",
        "agents": "agents",
    }
    api = modules["api"]
    assert api["languages"] == ["Python", "Docker"]
    assert [s["name"] for s in api["services"]] == ["api", "migrate", "scheduler", "worker"]
    # Its code is its package: not its tests, not its migrations.
    assert api["root"] == "api/leka"
    connectors = next(p for p in api["parts"] if p["name"] == "connectors")
    assert (connectors["files"], connectors["parts"], connectors["names"]) == (
        4,
        2,
        ["aws", "github"],
    )
    # What is installed or an editor's is no module; a template no agent.
    assert "node_modules" not in modules and ".vscode" not in modules
    assert not [p for p in modules["web"]["parts"] if p["name"] == "node_modules"]
    assert [p["name"] for p in modules["agents"]["parts"]] == ["incident"]
    assert modules["deploy"]["languages"] == ["Caddy", "Docker Compose"]
    assert modules["deploy"]["names"] == [
        "Caddyfile",
        "docker-compose.production.yml",
        "production.env.example",
    ]
    assert laid["files"] == len(set(TREE))
