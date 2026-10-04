"""What a repository's code says it runs (LEKA-369): its components.

A code host's connector hands this module a repository's files — those
WANTED of its tree, a few dozen at most — and gets back what they declare:

    services     what the repository's own code runs — an API, a web app,
                 a worker, a scheduler, a one-off job — and a proxy in
                 front of them; each with its technology, its code, where
                 it is reached
    data         what they keep data in: a database, a cache or queue, an
                 object store
    externals    what they call outside: an e-mail provider, a payment, an
                 AI or a monitoring service

and the LINKS between them, named — a proxy routes to a service, a web app
calls an API, a service keeps its queue in Redis, its data in PostgreSQL,
its files in S3, sends its e-mail through OVH — each with the file and the
line that says so.

WHERE IT IS READ — the files that say what runs, not what the code is:

    compose files      the services, their images, their dependencies and
                       environment; the one named for production when there
                       is one — a development compose's test databases are
                       not what the company runs
    env examples       what the services are configured with: a database's
                       URL, a bucket, an SMTP host — a value, or the example
                       its comment gives; an empty one is off
    proxy configs      Caddy's, nginx's: which service each address reaches
    CI workflows       which directory each image is built from, what a
                       build is told (an API's URL), what is deployed where
    Dockerfiles, package.json, pyproject.toml, requirements, go.mod
                       a service's language and framework

WHAT IS NEVER GUESSED. A library is not a database: an API that carries
pymongo to read its customers' MongoDB keeps nothing in MongoDB. A data
store comes from configuration only — a compose service, a connection URL
— and an external service from a configured value; a library says a
language or a framework, no more.

THE LAYOUT — what the repository is made of, from its tree alone (no file
read): its top-level folders as MODULES — the code of a service, the
documentation, the infrastructure, the CI, the agents, the scripts — each
with how many files and in what languages, and the parts of a service's
code (Leka's API: connectors — 31 of them — ingestion, knowledge…). The
role of a folder is what a service's code says of it, else its name.

Pure: files in, components out. Vendor-neutral: GitHub's, GitLab's,
Bitbucket's connectors hand it the same thing.
"""

from __future__ import annotations

import json
import posixpath
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import yaml

# A setting as an env example documents it: its value, the comment above
# it, its line, its file.
type Setting = tuple[str, str, int | None, str]

# What a pass reads of a repository, at most: the files, and each one's size.
MAX_FILES = 40
MAX_BYTES = 200_000

COMPOSE = re.compile(r"(^|/)(docker-)?compose([.-][\w.-]+)?\.ya?ml$", re.IGNORECASE)
DOCKERFILE = re.compile(r"(^|/)Dockerfile([.-][\w.-]+)?$")
WORKFLOW = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
ENV_EXAMPLE = re.compile(
    r"(^|/)(\.env\.(example|sample|template)|[\w.-]+\.env\.(example|sample|template)|env\.example)$"
)
PROXY = re.compile(r"(^|/)(Caddyfile|nginx[\w.-]*\.conf)$")
CODE_MANIFEST = re.compile(
    r"(^|/)(package\.json|pyproject\.toml|requirements[\w.-]*\.txt|go\.mod)$"
)
# What is not the company's running code: its dependencies, its builds,
# its tests and their fixtures.
SKIPPED = frozenset(
    {
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        "tests",
        "test",
        "__tests__",
        "e2e",
        "fixtures",
        "examples",
        "example",
        "docs",
    }
)

# Images that are not the company's code: what each is to its services.
IMAGES: dict[str, tuple[str, str, str]] = {
    # image: (kind, role, the engine or the technology)
    "postgres": ("database", "database", "postgresql"),
    "pgvector": ("database", "database", "postgresql"),
    "postgis": ("database", "database", "postgresql"),
    "timescaledb": ("database", "database", "postgresql"),
    "mysql": ("database", "database", "mysql"),
    "mariadb": ("database", "database", "mariadb"),
    "mongo": ("database", "database", "mongodb"),
    "mssql": ("database", "database", "sqlserver"),
    "oracle": ("database", "database", "oracle"),
    "oracle-free": ("database", "database", "oracle"),
    "clickhouse-server": ("database", "database", "clickhouse"),
    "cockroach": ("database", "database", "cockroachdb"),
    "redis": ("database", "cache", "redis"),
    "valkey": ("database", "cache", "valkey"),
    "keydb": ("database", "cache", "keydb"),
    "memcached": ("database", "cache", "memcached"),
    "rabbitmq": ("database", "queue", "rabbitmq"),
    "kafka": ("database", "queue", "kafka"),
    "nats": ("database", "queue", "nats"),
    "elasticsearch": ("database", "search", "elasticsearch"),
    "opensearch": ("database", "search", "opensearch"),
    "meilisearch": ("database", "search", "meilisearch"),
    "minio": ("storage", "storage", "minio"),
    "caddy": ("service", "proxy", "Caddy"),
    "nginx": ("service", "proxy", "nginx"),
    "traefik": ("service", "proxy", "Traefik"),
    "haproxy": ("service", "proxy", "HAProxy"),
    "envoy": ("service", "proxy", "Envoy"),
}
ENGINE_NAMES = {
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mongodb": "MongoDB",
    "sqlserver": "SQL Server",
    "oracle": "Oracle",
    "clickhouse": "ClickHouse",
    "cockroachdb": "CockroachDB",
    "redis": "Redis",
    "valkey": "Valkey",
    "keydb": "KeyDB",
    "memcached": "Memcached",
    "rabbitmq": "RabbitMQ",
    "kafka": "Kafka",
    "nats": "NATS",
    "elasticsearch": "Elasticsearch",
    "opensearch": "OpenSearch",
    "meilisearch": "Meilisearch",
    "minio": "MinIO",
}
# A connection URL's scheme: the engine it reaches.
SCHEMES = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "mongodb": "mongodb",
    "mongodb+srv": "mongodb",
    "mssql": "sqlserver",
    "sqlserver": "sqlserver",
    "oracle": "oracle",
    "redis": "redis",
    "rediss": "redis",
    "amqp": "rabbitmq",
    "amqps": "rabbitmq",
    "kafka": "kafka",
    "nats": "nats",
}
ROLE_OF_ENGINE = {"redis": "cache", "valkey": "cache", "keydb": "cache", "memcached": "cache"}
ROLE_OF_ENGINE |= {"rabbitmq": "queue", "kafka": "queue", "nats": "queue"}
# Frameworks, by a dependency's name: what a service is written with.
FRAMEWORKS = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "starlette": "Starlette",
    "aiohttp": "aiohttp",
    "rq": "RQ",
    "celery": "Celery",
    "dramatiq": "Dramatiq",
    "next": "Next.js",
    "react": "React",
    "vue": "Vue",
    "nuxt": "Nuxt",
    "svelte": "Svelte",
    "@sveltejs/kit": "SvelteKit",
    "@angular/core": "Angular",
    "express": "Express",
    "@nestjs/core": "NestJS",
    "fastify": "Fastify",
    "bullmq": "BullMQ",
    "github.com/gin-gonic/gin": "Gin",
    "github.com/labstack/echo/v4": "Echo",
}
# What a queue framework is to a worker; what a web framework is to an API.
QUEUE_FRAMEWORKS = frozenset({"RQ", "Celery", "Dramatiq", "BullMQ"})
FRONT_FRAMEWORKS = frozenset({"Next.js", "React", "Vue", "Nuxt", "Svelte", "SvelteKit", "Angular"})
# An e-mail provider by its SMTP host's domain.
MAIL_HOSTS = {
    "ovh.net": "OVH",
    "sendgrid.net": "SendGrid",
    "mailgun.org": "Mailgun",
    "amazonaws.com": "Amazon SES",
    "postmarkapp.com": "Postmark",
    "mailjet.com": "Mailjet",
    "sendinblue.com": "Brevo",
    "brevo.com": "Brevo",
    "gmail.com": "Google",
    "googlemail.com": "Google",
    "office365.com": "Microsoft 365",
    "outlook.com": "Microsoft 365",
    "resend.com": "Resend",
    "sparkpostmail.com": "SparkPost",
}
# Services outside, by what configures them: the variable's words, the
# vendor, what it is to the company.
EXTERNALS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"SENTRY_DSN$"), "Sentry", "monitoring"),
    (re.compile(r"STRIPE_(SECRET|API)_KEY$"), "Stripe", "payments"),
    (re.compile(r"OPENAI_API_KEY$"), "OpenAI", "ai"),
    (re.compile(r"ANTHROPIC_API_KEY$"), "Anthropic", "ai"),
    (re.compile(r"SENDGRID_API_KEY$"), "SendGrid", "email"),
    (re.compile(r"TWILIO_AUTH_TOKEN$"), "Twilio", "messaging"),
    (re.compile(r"SLACK_(BOT_)?TOKEN$"), "Slack", "messaging"),
    (re.compile(r"DATADOG_API_KEY$|DD_API_KEY$"), "Datadog", "monitoring"),
    (re.compile(r"SEGMENT_WRITE_KEY$"), "Segment", "analytics"),
)
# What a front end is told of the API it calls.
API_URL = re.compile(r"(^|_)API(_BASE)?_URL$")
# What a proxy reaches: `reverse_proxy web:3000`, `proxy_pass http://api:8000;`.
CADDY_PROXY = re.compile(r"^\s*reverse_proxy\s+(\S+)")
NGINX_PROXY = re.compile(r"proxy_pass\s+https?://([\w.-]+)(?::\d+)?")
COMPOSE_VAR = re.compile(r"\$\{([A-Z0-9_]+)(:?[-?][^}]*)?\}|\$([A-Z0-9_]+)")
CADDY_VAR = re.compile(r"\{\$([A-Z0-9_]+)\}")
ROLES_OF_NAME = (
    (re.compile(r"migrat"), "job"),
    (re.compile(r"worker|consumer"), "worker"),
    (re.compile(r"schedul|cron|beat"), "scheduler"),
)
ACRONYMS = frozenset({"api", "ui", "db", "cdn", "sso"})
SSH_ACTIONS = ("appleboy/ssh-action", "appleboy/scp-action")


@dataclass
class Component:
    """One thing a repository runs, or that what it runs relies on."""

    name: str
    kind: str  # service, database, storage, external
    role: str
    display_name: str
    environment: str | None = None
    technology: list[str] = field(default_factory=list)
    engine: str | None = None
    provider: str | None = None
    region: str | None = None
    vendor: str | None = None
    image: str | None = None
    code_path: str | None = None
    public_url: str | None = None
    ports: list[str] = field(default_factory=list)
    deployed_by: str | None = None
    deploy_method: str | None = None
    # Its code queues jobs: RQ, Celery, BullMQ among its dependencies.
    queues: bool = False
    links: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    evidence: list[dict[str, object]] = field(default_factory=list)

    def link(self, to: str, role: str, evidence: str) -> None:
        """A link to another of the repository's components — the more
        telling role kept when two files say it: a queue is more than a
        dependency."""
        if to == self.name:
            return
        known = [k for k in self.links if k[0] == to]
        if known and LINK_RANK.get(role, 0) <= LINK_RANK.get(known[0][1], 0):
            return
        for k in known:
            del self.links[k]
        self.links[(to, role)] = {"to": to, "role": role, "evidence": evidence}

    def said(self, path: str, line: int | None, says: str) -> None:
        self.evidence.append({"path": path, "line": line, "says": says})

    def payload(self, repository: str) -> dict[str, object]:
        return {
            "repository": repository,
            "name": self.name,
            "kind": self.kind,
            "role": self.role,
            "display_name": self.display_name,
            "environment": self.environment,
            "technology": self.technology,
            "engine": self.engine,
            "provider": self.provider,
            "region": self.region,
            "vendor": self.vendor,
            "image": self.image,
            "code_path": self.code_path,
            "public_url": self.public_url,
            "ports": self.ports,
            "deployed_by": self.deployed_by,
            "deploy_method": self.deploy_method,
            "links": [],
            "evidence": self.evidence[:20],
        }


# A link's roles, the more telling higher: a dependency that is a queue is
# a queue.
LINK_RANK = {"depends": 0, "uses": 1, "calls": 2, "routes": 2, "stores": 3, "queue": 3}
LINK_RANK |= {"cache": 3, "files": 3, "email": 3}


def wanted(paths: Iterable[str]) -> list[str]:
    """The files of a tree that say what it runs — compose files, workflows,
    env examples and proxy configs first, then code manifests, then
    Dockerfiles — MAX_FILES at most, none in a dependency, a build or a
    test."""
    first: list[str] = []
    manifests: list[str] = []
    then: list[str] = []
    for path in sorted(paths):
        parts = path.split("/")
        if any(part in SKIPPED for part in parts[:-1]):
            continue
        if any(p.search(path) for p in (COMPOSE, WORKFLOW, ENV_EXAMPLE, PROXY)):
            first.append(path)
        elif CODE_MANIFEST.search(path):
            manifests.append(path)
        elif DOCKERFILE.search(path):
            then.append(path)
    return [*first, *manifests, *then][:MAX_FILES]


def discover(repository: str, files: Mapping[str, str]) -> list[dict[str, object]]:
    """The components a repository's files declare, each with its links and
    where each thing was read."""
    return Discovery(repository, files).run()


# ── how ─────────────────────────────────────────────────────────────────────


# The layout's bounds: modules, the parts of one, the names of a part's own.
MAX_MODULES = 20
MAX_PARTS = 30
MAX_NAMES = 40
# What is never a module: what is installed, built or cached.
NOT_MODULES = frozenset(
    {
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        "__pycache__",
        "coverage",
        ".git",
        ".idea",
        ".vscode",
    }
)
# Beside a service's code, not its code: its migrations.
NOT_CODE = frozenset({"alembic", "migrations", "migration"})
# A folder's role, by its name: what most repositories call these.
FOLDER_ROLES: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"docs", "doc", "documentation", "wiki"}), "docs"),
    (
        frozenset(
            {
                "deploy",
                "deployment",
                "deployments",
                "infra",
                "infrastructure",
                "terraform",
                "k8s",
                "kubernetes",
                "helm",
                "charts",
                "ops",
                "ansible",
            }
        ),
        "infrastructure",
    ),
    (frozenset({".github", ".gitlab", ".circleci", ".buildkite"}), "ci"),
    (frozenset({"agents", "agent", "prompts", "skills"}), "agents"),
    (frozenset({"scripts", "bin", "tools"}), "scripts"),
    (frozenset({"tests", "test", "e2e", "spec"}), "tests"),
)
# A language, by a file's extension or name.
LANGUAGES = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".rs": "Rust",
    ".cs": "C#",
    ".swift": "Swift",
    ".md": "Markdown",
    ".mdx": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
    ".tf": "Terraform",
    ".css": "CSS",
    ".html": "HTML",
    ".yml": "YAML",
    ".yaml": "YAML",
}
NAMED_LANGUAGES = {"Dockerfile": "Docker", "Caddyfile": "Caddy", "Makefile": "Make"}
# What says a little of a module, not its language: shown only when alone.
MINOR_LANGUAGES = frozenset({"YAML", "Markdown", "CSS", "HTML", "Shell"})


def layout(
    paths: Iterable[str], components: Iterable[Mapping[str, object]] = ()
) -> dict[str, object]:
    """What a repository is made of, from its tree's paths: its modules —
    its top-level folders, each with its role, its files, its languages,
    the services whose code it is, and its parts."""
    files = sorted({p for p in paths if p and not p.endswith("/")})
    code_paths: dict[str, list[tuple[str, str]]] = {}
    for component in components:
        where = component.get("code_path")
        if isinstance(where, str) and where and component.get("kind") == "service":
            code_paths.setdefault(where.strip("/"), []).append(
                (str(component.get("name")), str(component.get("role") or ""))
            )
    tops: dict[str, list[str]] = {}
    for path in files:
        top, _, rest = path.partition("/")
        if not rest or top in NOT_MODULES or (top.startswith(".") and _folder_role(top) is None):
            continue
        tops.setdefault(top, []).append(path)
    modules = [
        _module(top, inside, code_paths)
        for top, inside in sorted(tops.items(), key=lambda item: (-len(item[1]), item[0]))
    ][:MAX_MODULES]
    return {"modules": modules, "files": len(files)}


def _module(
    top: str, inside: list[str], code_paths: Mapping[str, list[tuple[str, str]]]
) -> dict[str, object]:
    served = [
        served
        for path, found in code_paths.items()
        for served in found
        if path == top or path.startswith(f"{top}/")
    ]
    role = "service" if served else (_folder_role(top) or "code")
    root = _source_root(top, inside)
    parts: list[dict[str, object]] = []
    below: dict[str, list[str]] = {}
    for path in inside:
        rest = path[len(root) + 1 :] if path.startswith(f"{root}/") else None
        if rest and "/" in rest:
            below.setdefault(rest.split("/", 1)[0], []).append(path)
    for name, held in sorted(below.items(), key=lambda item: (-len(item[1]), item[0])):
        if name in NOT_MODULES or name.startswith((".", "_")):
            continue
        children = sorted(
            {
                p[len(root) + len(name) + 2 :].split("/", 1)[0]
                for p in held
                if "/" in p[len(root) + len(name) + 2 :]
            }
            - NOT_MODULES
        )
        children = [c for c in children if not c.startswith(("_", "."))]
        parts.append(
            {
                "name": name,
                "path": f"{root}/{name}",
                "files": len(held),
                "parts": len(children),
                "names": children[:MAX_NAMES],
            }
        )
    # A small module says its files: deploy's compose, Caddyfile, script.
    named = sorted(p[len(top) + 1 :] for p in inside) if len(inside) <= 8 else []
    return {
        "path": top,
        "role": role,
        "files": len(inside),
        "languages": _languages(inside),
        "services": [{"name": name, "role": what} for name, what in served],
        "root": root,
        "parts": parts[:MAX_PARTS],
        "names": named,
    }


def _folder_role(name: str) -> str | None:
    folded = name.lower()
    return next((role for names, role in FOLDER_ROLES if folded in names), None)


def _source_root(top: str, inside: list[str]) -> str:
    """Where a module's own code starts: Python's package — api/leka —
    else its src, else the module."""
    packages = sorted(
        {posixpath.dirname(p) for p in inside if posixpath.basename(p) == "__init__.py"},
        key=lambda d: (d.count("/"), d),
    )
    # Its tests and its migrations are beside its code, not its code.
    tops = [
        d
        for d in packages
        if posixpath.dirname(d) not in packages
        and d != top
        and _folder_role(posixpath.basename(d)) != "tests"
        and posixpath.basename(d) not in NOT_CODE
    ]
    shallow = [d for d in tops if d.count("/") == (tops[0].count("/") if tops else 0)]
    if len(shallow) == 1:
        return shallow[0]
    if any(p.startswith(f"{top}/src/") for p in inside):
        return f"{top}/src"
    return top


def _languages(paths: Iterable[str]) -> list[str]:
    counted: dict[str, int] = {}
    for path in paths:
        base = posixpath.basename(path)
        language = (
            "Docker Compose"
            if COMPOSE.search(path)
            else "GitHub Actions"
            if WORKFLOW.search(path)
            else NAMED_LANGUAGES.get(base) or LANGUAGES.get(posixpath.splitext(base)[1].lower())
        )
        if language:
            counted[language] = counted.get(language, 0) + 1
    ranked = sorted(counted, key=lambda language: (-counted[language], language))
    major = [language for language in ranked if language not in MINOR_LANGUAGES]
    return (major or ranked)[:3]


@dataclass
class Build:
    """What a CI workflow builds and ships."""

    images: dict[str, str] = field(default_factory=dict)  # image → its code's directory
    build_args: dict[str, list[tuple[str, str]]] = field(
        default_factory=dict
    )  # image → (arg, path)
    shipped: dict[str, tuple[str, str | None, str]] = field(default_factory=dict)


class Discovery:
    def __init__(self, repository: str, files: Mapping[str, str]) -> None:
        self.repository = repository
        self.short = repository.rsplit("/", 1)[-1]
        self.files = {path: text for path, text in files.items() if isinstance(text, str)}
        self.components: dict[str, Component] = {}
        self.ci = Build()

    def run(self) -> list[dict[str, object]]:
        for path in sorted(self.files):
            if WORKFLOW.search(path):
                self._workflow(path)
        for path in self._composes():
            self._compose(path)
        found = sorted(self.components.values(), key=_order)
        return [self._payload(component) for component in found]

    def _payload(self, component: Component) -> dict[str, object]:
        """A component as a record says it — each link with what it reaches,
        so that what reads the record can name it without the others."""
        payload = component.payload(self.repository)
        links = []
        for link in component.links.values():
            target = self.components.get(link["to"])
            if target is None:
                continue
            links.append(
                {
                    **link,
                    "kind": target.kind,
                    "display_name": target.display_name,
                    "engine": target.engine,
                    "vendor": target.vendor,
                }
            )
        payload["links"] = sorted(links, key=lambda link: (str(link["to"]), str(link["role"])))
        return payload

    # ── workflows ───────────────────────────────────────────────────────────

    def _workflow(self, path: str) -> None:
        document = _yaml(self.files[path])
        jobs = document.get("jobs") if isinstance(document, dict) else None
        if not isinstance(jobs, dict):
            return
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            environment = job.get("environment")
            if isinstance(environment, dict):
                environment = environment.get("name")
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                uses = str(step.get("uses") or "")
                said = step.get("with")
                given: Mapping[str, Any] = said if isinstance(said, dict) else {}
                if uses.startswith("docker/build-push-action"):
                    self._built(path, given)
                if uses.startswith(SSH_ACTIONS) and isinstance(environment, str):
                    for sent in str(given.get("source") or "").split(","):
                        sent = sent.strip()
                        if sent:
                            self.ci.shipped[sent] = (path, environment.lower(), "ssh")

    def _built(self, path: str, given: Mapping[str, Any]) -> None:
        context = str(given.get("context") or ".").strip().strip("./") or "."
        for tag in re.split(r"[\s,]+", str(given.get("tags") or "")):
            image = _image_name(tag)
            if not image:
                continue
            self.ci.images[image] = context
            for line in str(given.get("build-args") or "").splitlines():
                name = line.split("=", 1)[0].strip()
                if name:
                    self.ci.build_args.setdefault(image, []).append((name, path))

    # ── compose ─────────────────────────────────────────────────────────────

    def _composes(self) -> list[str]:
        """The compose files that say what runs: those named for production
        when there are some — then staging — else every one not a test's."""
        found = [p for p in sorted(self.files) if COMPOSE.search(p)]
        named = {p: _environment_of(p) for p in found}
        for wanted_env in ("production", "staging"):
            chosen = [p for p in found if named[p] == wanted_env]
            if chosen:
                return chosen
        return [p for p in found if named[p] not in ("test", "development")] or [
            p for p in found if named[p] != "test"
        ]

    def _compose(self, path: str) -> None:
        text = self.files[path]
        document = _yaml(text)
        services = document.get("services") if isinstance(document, dict) else None
        if not isinstance(services, dict):
            return
        environment = _environment_of(path) or self._shipped_env(path)
        directory = posixpath.dirname(path)
        variables = self._variables(directory)
        shipped = self.ci.shipped.get(path)
        names = {str(name) for name in services}
        made: list[tuple[Component, Mapping[str, Any]]] = []
        for name, spec in services.items():
            if not isinstance(spec, dict):
                continue
            component = self._service(path, str(name), spec, environment)
            if shipped:
                component.deployed_by, _, component.deploy_method = shipped
            made.append((component, spec))
        # Every service known before any is linked: a dependency named
        # below its dependent is still what it is.
        for component, spec in made:
            # What configures it first: a setting says more than an order
            # to start in — the queue's URL rather than `depends_on`.
            self._environment(path, component, spec, directory, names, variables)
            self._depends(path, component, spec, names)
        self._proxies(path, directory, variables)
        self._calls(environment)

    def _service(
        self, path: str, name: str, spec: Mapping[str, Any], environment: str | None
    ) -> Component:
        image_ref = str(spec.get("image") or "")
        image = _image_name(image_ref)
        build = spec.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        code_path = (
            posixpath.normpath(posixpath.join(posixpath.dirname(path), str(context)))
            if isinstance(context, str)
            else self.ci.images.get(image or "")
            or (image if image and self._has_dockerfile(image) else None)
        )
        third = None if code_path else IMAGES.get(image or "")
        line = _line(self.files[path], rf"^\s+{re.escape(name)}:\s*$")
        if third is not None:
            kind, role, what = third
            # A store keeps its engine's name; a proxy the repository runs is
            # the repository's — two repositories' Caddy are two.
            component = self._component(
                name,
                kind,
                role,
                ENGINE_NAMES.get(what, what) if kind != "service" else self._named(name),
                environment,
            )
            if kind == "service":
                component.technology = [what]
            else:
                component.engine = what
            component.image = image_ref.split("@", 1)[0] or None
        else:
            role = _role_of(name, spec)
            component = self._component(name, "service", role, self._named(name), environment)
            component.image = image
            component.code_path = code_path if code_path not in (None, ".") else None
            component.technology, component.queues = self._technology(code_path, role)
            if role in ("service", "api") and component.technology:
                component.role = (
                    "web" if any(t in FRONT_FRAMEWORKS for t in component.technology) else "api"
                )
        component.ports = [
            str(p) for p in (spec.get("ports") or spec.get("expose") or []) if p is not None
        ]
        component.said(path, line, f"the service {name}")
        return component

    def _depends(
        self, path: str, component: Component, spec: Mapping[str, Any], names: set[str]
    ) -> None:
        depends = spec.get("depends_on") or []
        for other in depends if isinstance(depends, list) else list(depends):
            other = str(other)
            target = self.components.get(other)
            # Waiting for a one-off job — a migration — is an order to
            # start in, not a dependency of what runs.
            if other in names and target is not None and target.role != "job":
                component.link(other, _role_to(target, component), f"{path} — depends_on {other}")

    def _environment(
        self,
        path: str,
        component: Component,
        spec: Mapping[str, Any],
        directory: str,
        names: set[str],
        variables: Mapping[str, Setting],
    ) -> None:
        """What a service is configured with: its compose environment, and
        the env files it reads, as their examples document them."""
        configured: dict[str, Setting] = {}
        for env_file in _list(spec.get("env_file")):
            example = self._example_of(directory, str(env_file))
            if example is not None:
                for key, (value, comment, line, where) in self._read_env(example).items():
                    configured[key] = (value, comment, line, where)
        environment = spec.get("environment") or {}
        pairs: list[tuple[str, str]] = []
        if isinstance(environment, dict):
            pairs = [(str(k), "" if v is None else str(v)) for k, v in environment.items()]
        else:
            for item in environment:
                name, _, value = str(item).partition("=")
                pairs.append((name, value))
        for key, text in pairs:
            if COMPOSE_VAR.fullmatch(text.strip()) and key in variables:
                configured.setdefault(key, variables[key])
                continue
            configured[key] = (text, "", _line(self.files[path], rf"\b{key}\b"), path)
        for key, (value, comment, line, where) in configured.items():
            self._configured(
                component, key, value, comment, f"{where}:{line}" if line else where, names
            )

    def _configured(
        self,
        component: Component,
        key: str,
        value: str,
        comment: str,
        where: str,
        names: set[str],
    ) -> None:
        """One setting of a service: a store it keeps data in, a service
        outside it calls — or nothing this module knows."""
        url = value if "://" in value else _url_in(comment) if key.endswith("_URL") else None
        if url:
            scheme = urlsplit(url).scheme.split("+", 1)[0].lower()
            engine = SCHEMES.get(scheme)
            host = urlsplit(url).hostname or ""
            if engine is None:
                return
            if host in names:
                component.link(host, _store_role(engine, component), f"{where} — {key}")
                return
            store = self._component(
                engine,
                "database",
                ROLE_OF_ENGINE.get(engine, "database"),
                ENGINE_NAMES[engine],
                component.environment,
            )
            store.engine = engine
            store.said(where.split(":", 1)[0], _int(where), f"{key}: {ENGINE_NAMES[engine]}")
            component.link(store.name, _store_role(engine, component), f"{where} — {key}")
            return
        if key.endswith("OBJECT_STORE") and value.strip().lower() == "s3":
            store = self._component("s3", "storage", "storage", "S3", component.environment)
            store.provider = "aws"
            store.said(where.split(":", 1)[0], _int(where), f"{key}=s3")
            component.link("s3", "files", f"{where} — {key}")
            return
        if key.endswith("S3_REGION") and value.strip() and "s3" in self.components:
            self.components["s3"].region = value.strip()
            return
        if key.endswith("SMTP_HOST") and value.strip():
            vendor = _mail_vendor(value.strip())
            name = f"{_slug(vendor)}-mail"
            mail = self._component(
                name, "external", "email", f"{vendor} (e-mail)", component.environment
            )
            mail.vendor = vendor
            mail.said(where.split(":", 1)[0], _int(where), f"{key}={value.strip()}")
            component.link(name, "email", f"{where} — {key}")
            return
        for pattern, vendor, role in EXTERNALS:
            if pattern.search(key) and value.strip() and not value.strip().startswith(("<", "$")):
                name = _slug(vendor)
                outside = self._component(name, "external", role, vendor, component.environment)
                outside.vendor = vendor
                outside.said(where.split(":", 1)[0], _int(where), key)
                component.link(name, "uses", f"{where} — {key}")
                return

    # ── proxies, calls ──────────────────────────────────────────────────────

    def _proxies(self, compose: str, directory: str, variables: Mapping[str, Setting]) -> None:
        """A proxy's config, beside its compose file: which service each of
        its addresses reaches."""
        proxies = [c for c in self.components.values() if c.role == "proxy"]
        if not proxies:
            return
        for path in sorted(self.files):
            if not PROXY.search(path) or posixpath.dirname(path) != directory:
                continue
            for target, site, line in _proxy_routes(self.files[path]):
                reached = self.components.get(target)
                if reached is None:
                    continue
                for proxy in proxies:
                    proxy.link(target, "routes", f"{path}:{line} — {target}")
                address = _resolve(site, variables)
                if address and not reached.public_url:
                    reached.public_url = f"https://{address}"
                    reached.said(path, line, f"reached at {address}")

    def _calls(self, environment: str | None) -> None:
        """A front end told its API's URL — a build argument, a setting —
        calls the repository's API."""
        apis = [
            c for c in self.components.values() if c.role == "api" and c.environment == environment
        ]
        if len(apis) != 1:
            return
        api = apis[0]
        for front in self.components.values():
            if front.role != "web" or front.environment != environment:
                continue
            told = [
                (arg, path)
                for arg, path in self.ci.build_args.get(front.image or "", [])
                if API_URL.search(arg)
            ]
            if told:
                arg, path = told[0]
                front.link(api.name, "calls", f"{path} — {arg}")

    # ── helpers ─────────────────────────────────────────────────────────────

    def _component(
        self, name: str, kind: str, role: str, display: str, environment: str | None
    ) -> Component:
        known = self.components.get(name)
        if known is None:
            known = self.components[name] = Component(
                name=name, kind=kind, role=role, display_name=display, environment=environment
            )
        return known

    def _named(self, name: str) -> str:
        """`api` of Leka is Leka API; `web`, Leka Web."""
        words = " ".join(
            w.upper() if w in ACRONYMS else w.capitalize() for w in re.split(r"[-_\s]+", name) if w
        )
        return f"{self.short[:1].upper()}{self.short[1:]} {words}".strip()

    def _has_dockerfile(self, directory: str) -> bool:
        return f"{directory}/Dockerfile" in self.files

    def _technology(self, code_path: str | None, role: str) -> tuple[list[str], bool]:
        """A service's language and frameworks, from its code's manifests and
        its Dockerfile — a worker's queue framework, not its web one — and
        whether its code queues jobs."""
        if not code_path:
            return [], False
        found: list[str] = []
        prefix = "" if code_path == "." else f"{code_path}/"
        pyproject = self.files.get(f"{prefix}pyproject.toml")
        requirements = [
            text
            for path, text in self.files.items()
            if posixpath.dirname(path) == prefix.rstrip("/")
            and re.match(r"requirements[\w.-]*\.txt$", posixpath.basename(path))
        ]
        package = self.files.get(f"{prefix}package.json")
        gomod = self.files.get(f"{prefix}go.mod")
        names: list[str] = []
        if pyproject is not None or requirements:
            found.append("Python")
            names += _python_dependencies(pyproject, requirements)
        if package is not None:
            names += _node_dependencies(package)
            found.append("TypeScript" if "typescript" in names else "JavaScript")
        if gomod is not None:
            found.append("Go")
            # `require x v1` alone, or each line of a `require (...)` block.
            names += re.findall(r"^\s*(?:require\s+)?([\w./-]+)\s+v\d", gomod, re.MULTILINE)
        frameworks = list(dict.fromkeys(FRAMEWORKS[n] for n in names if n in FRAMEWORKS))
        queues = any(f in QUEUE_FRAMEWORKS for f in frameworks)
        if role == "worker":
            frameworks = [f for f in frameworks if f in QUEUE_FRAMEWORKS]
        elif role in ("scheduler", "job"):
            frameworks = []
        else:
            frameworks = [f for f in frameworks if f not in QUEUE_FRAMEWORKS]
        if not found:
            dockerfile = self.files.get(f"{prefix}Dockerfile", "")
            base = re.search(r"^\s*FROM\s+([\w./-]+)", dockerfile, re.MULTILINE | re.IGNORECASE)
            if base:
                found.append(base.group(1).rsplit("/", 1)[-1].capitalize())
        return [*found, *frameworks], queues

    def _variables(self, directory: str) -> dict[str, Setting]:
        """What the env examples beside a compose file say each variable is:
        what its `${VAR}` stands for."""
        found: dict[str, Setting] = {}
        for path in sorted(self.files):
            if ENV_EXAMPLE.search(path) and posixpath.dirname(path) == directory:
                for key, entry in self._read_env(path).items():
                    found.setdefault(key, entry)
        return found

    def _example_of(self, directory: str, env_file: str) -> str | None:
        """An env file a service reads — never committed — by its example."""
        base = posixpath.normpath(posixpath.join(directory, env_file))
        for candidate in (f"{base}.example", f"{base}.sample", f"{base}.template"):
            if candidate in self.files:
                return candidate
        return None

    def _read_env(self, path: str) -> dict[str, Setting]:
        """KEY=value lines, each with the comment above it — where an example
        of an empty value is often given."""
        found: dict[str, Setting] = {}
        comment: list[str] = []
        for number, raw in enumerate(self.files[path].splitlines(), start=1):
            line = raw.strip()
            if not line:
                comment = []
            elif line.startswith("#"):
                comment.append(line.lstrip("#").strip())
            elif "=" in line:
                key, value = line.split("=", 1)
                found[key.strip()] = (
                    value.strip().strip('"').strip("'"),
                    " ".join(comment),
                    number,
                    path,
                )
                comment = []
        return found

    def _shipped_env(self, path: str) -> str | None:
        shipped = self.ci.shipped.get(path)
        return shipped[1] if shipped else None


def _order(component: Component) -> tuple[int, str]:
    return (
        {"service": 0, "database": 1, "storage": 2, "external": 3}.get(component.kind, 4),
        component.name,
    )


def _role_of(name: str, spec: Mapping[str, Any]) -> str:
    """What a service of the company's code is, by its name and command."""
    said = f"{name} {spec.get('command') or ''} {spec.get('entrypoint') or ''}".lower()
    for pattern, role in ROLES_OF_NAME:
        if pattern.search(said):
            return role
    if str(spec.get("restart") or "") == "no":
        return "job"
    return "service"


def _role_to(target: Component, source: Component) -> str:
    """A dependency's role, by what it depends on — and what depends: a
    service whose code queues jobs keeps a queue in Redis, not a cache."""
    if target.kind == "database":
        return _store_role(target.engine or "", source)
    if target.kind == "storage":
        return "files"
    return "depends"


def _store_role(engine: str, source: Component) -> str:
    role = ROLE_OF_ENGINE.get(engine, "stores")
    return "queue" if role == "cache" and source.queues else role


def _environment_of(path: str) -> str | None:
    name = posixpath.basename(path).lower()
    if re.search(r"prod", name):
        return "production"
    if re.search(r"stag", name):
        return "staging"
    if re.search(r"(^|[.-])(test|ci)([.-]|$)", name):
        return "test"
    if re.search(r"(^|[.-])(dev|local|override)([.-]|$)", name):
        return "development"
    return None


def _image_name(reference: str) -> str | None:
    """`${REGISTRY}/api:${RELEASE}` → api; `redis:7-alpine` → redis;
    `ghcr.io/acme/web@sha256:…` → web."""
    plain = COMPOSE_VAR.sub("", reference).strip()
    plain = re.sub(r"\$\{\{[^}]*\}\}", "", plain)
    plain = plain.split("@", 1)[0]
    last = plain.rstrip("/").rsplit("/", 1)[-1]
    name = last.split(":", 1)[0].strip().lower()
    return name or None


def _proxy_routes(text: str) -> list[tuple[str, str, int]]:
    """A proxy's routes: (the service reached, the address it answers, the
    line) — Caddy's sites and nginx's proxy_pass."""
    routes: list[tuple[str, str, int]] = []
    site = ""
    for number, line in enumerate(text.splitlines(), start=1):
        head = line.rstrip()
        if (
            head.endswith("{")
            and not line.startswith(("\t", " "))
            and head != "{"
            and not head.startswith(("(", "#"))
        ):
            site = head[:-1].split()[0]
        proxied = CADDY_PROXY.match(line)
        if proxied:
            routes.append((proxied.group(1).split(":", 1)[0], site, number))
        for target in NGINX_PROXY.findall(line):
            routes.append((target, "", number))
    return routes


def _resolve(site: str, variables: Mapping[str, Setting]) -> str | None:
    """A Caddy site's address, its `{$VAR}` replaced by the example's value."""
    if not site or site.startswith(("(", ":")):
        return None
    resolved = CADDY_VAR.sub(lambda m: variables.get(m.group(1), ("",))[0], site)
    resolved = resolved.split(",", 1)[0].strip()
    if not resolved or "{" in resolved or "$" in resolved:
        return None
    return resolved.removeprefix("https://").removeprefix("http://").rstrip("/") or None


def _mail_vendor(host: str) -> str:
    for domain, vendor in MAIL_HOSTS.items():
        if host.lower().endswith(domain):
            return vendor
    parts = host.lower().split(".")
    return parts[-2].capitalize() if len(parts) >= 2 else host


def _python_dependencies(pyproject: str | None, requirements: list[str]) -> list[str]:
    names: list[str] = []
    if pyproject:
        try:
            data = tomllib.loads(pyproject)
        except tomllib.TOMLDecodeError:
            data = {}
        project = data.get("project") if isinstance(data, dict) else None
        listed = project.get("dependencies") if isinstance(project, dict) else None
        poetry = (
            data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            if isinstance(data, dict)
            else {}
        )
        for spec in [*(listed or []), *(poetry or {})]:
            names.append(re.split(r"[\s\[<>=!~;]", str(spec), maxsplit=1)[0].lower())
    for text in requirements:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")):
                names.append(re.split(r"[\s\[<>=!~;]", line, maxsplit=1)[0].lower())
    return names


def _node_dependencies(package: str) -> list[str]:
    try:
        data = json.loads(package)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    for section in ("dependencies", "devDependencies"):
        listed = data.get(section)
        if isinstance(listed, dict):
            names += [str(n).lower() for n in listed]
    return names


def _yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _line(text: str, pattern: str) -> int | None:
    found = re.search(pattern, text, re.MULTILINE)
    return text.count("\n", 0, found.start()) + 1 if found else None


def _url_in(comment: str) -> str | None:
    found = re.search(r"\b([a-z][a-z0-9+.-]*://\S+)", comment)
    return found.group(1) if found else None


def _int(where: str) -> int | None:
    tail = where.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _list(value: object) -> list[object]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
