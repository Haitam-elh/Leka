"""A deliverable held to the code (2026-10-31): a database review listed
« critical missing indexes » the repository creates, « 117 migrations »
where there are 102, an N+1 in a file it marked « not read » — and said
LEKA's own database « without tables » because it is not connected.

What these protect:
- An index said missing that the code declares — by its migration, its
  model, or the very name proposed — is contradicted, with where; one the
  code does not have is not. A count of files that is not the count, a
  finding on a file said not read: contradicted. What a deliverable puts
  under « Ce qui n'a pas pu être vérifié » or « À mesurer » is not a claim.
- Told, the agent corrects it; still contradicted, the reader is told at
  the end of the deliverable — never left as if it held.
- A database LEKA does not read itself is said not connected, its tables
  unknown — never « empty ».
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from leka.capabilities import execute_run, sync_catalogue
from leka.capabilities import runs as runs_module
from leka.capabilities.deliverable_check import contradicted, contradictions_said
from leka.core.config import settings
from leka.intelligence import library
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import Script, gemini, leka_gemini, queued  # noqa: F401
from tests.test_code_changes_api import REPO, _github_source, github  # noqa: F401
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

RUNS = "/api/v1/agent-runs"
MIGRATION = """def upgrade() -> None:
    op.create_table(
        "memberships",
        sa.Column("workspace_id", sa.UUID()),
        sa.Column("user_id", sa.UUID()),
        sa.Column("role", sa.String()),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_workspace_role", "memberships", ["workspace_id", "role"])
    op.create_table(
        "entities",
        # the source's own id, as its connector said it
        sa.Column("source_id", sa.UUID()),
        sa.Column("key", sa.String()),
    )
    op.create_index("ix_entities_key", "entities", ["key"])


def downgrade() -> None:
    op.drop_table("entities")
"""
LATER = """def upgrade() -> None:
    op.drop_index("ix_entities_key", table_name="entities")
    op.drop_column("entities", "source_id")


def downgrade() -> None:
    op.add_column("entities", sa.Column("source_id", sa.UUID()))
"""
MODELS = """class Account(Base):
    __tablename__ = "accounts"

    owner_id = mapped_column(ForeignKey("users.id"), index=True)
    region = mapped_column(String(20))
"""
FILES = {
    "api/alembic/versions/001_initial.py": MIGRATION,
    "api/alembic/versions/002_more.py": LATER,
    "api/alembic/versions/__init__.py": "",
    "app/models.py": MODELS,
}


def test_an_index_said_missing_that_the_code_declares_is_contradicted_with_where() -> None:
    review = "\n".join(
        [
            "## Index manquants (critiques)",
            "| Table | Colonne | Preuve | Correction |",
            "|---|---|---|---|",
            "| `memberships` | `user_id` | migration 001 | "
            "`CREATE INDEX ix_memberships_user_id ON memberships(user_id)` |",
            # In an index, not first: no index serves it alone — it holds.
            "| `memberships` | `role` | composite | `CREATE INDEX ON memberships(role)` |",
            # Its index dropped since: it holds.
            "| `entities` | `key` | dropped | `CREATE INDEX ON entities(key)` |",
            "| `entities` | `source_id` | migration 001 | `CREATE INDEX ON entities(source_id)` |",
            "| `entities` | `owner` | guessed | `CREATE INDEX ON entities(owner)` |",
            # A table no migration makes: the code says nothing for sure.
            "| `accounts` | `region` | `app/models.py:5` | `CREATE INDEX ON accounts(region)` |",
            "## Requêtes",
            "- `accounts.owner_id` n'a aucun index : chaque jointure lit toute la table.",
        ]
    )
    found = contradicted(review, FILES)
    assert [(c.kind, c.said, c.path, c.line, c.evidence) for c in found] == [
        (
            "index",
            "memberships.user_id",
            "api/alembic/versions/001_initial.py",
            8,
            'op.create_index("ix_memberships_user_id", "memberships", ["user_id"])',
        ),
        ("column", "entities.source_id", "api/alembic/versions/002_more.py", 3, "dropped"),
        ("column", "entities.owner", "api/alembic/versions/001_initial.py", 10, ""),
        (
            "index",
            "accounts.owner_id",
            "app/models.py",
            4,
            'owner_id = mapped_column(ForeignKey("users.id"), index=True)',
        ),
    ]
    told = [c.to_model() for c in found]
    assert told[0].startswith("You say memberships.user_id has no index, but")
    assert "correct or remove that point" in told[0]
    assert "that column no longer exists: api/alembic/versions/002_more.py:3 drops it" in told[1]
    assert "no migration of the repository makes that column" in told[2]
    said = contradictions_said(found)
    assert "- `entities.source_id` : cette colonne n'existe plus" in said
    assert "- `entities.owner` : cette colonne n'existe pas dans le code" in said


def test_a_count_that_is_not_the_count_and_a_finding_on_a_file_not_read() -> None:
    review = "\n".join(
        [
            "## Code analysé",
            "- **Migrations** : 117 fichiers dans `api/alembic/versions/`.",
            "## Requêtes problématiques",
            "| Fichier | Ligne | Problème |",
            "|---|---|---|",
            "| `api/leka/identity/repository.py` | *Non lu* | **N+1 possible** |",
            "## Ce qui n'a pas pu être vérifié",
            "- `identity/repository.py` non lu ; un index manquant sur `accounts.owner_id` ?",
        ]
    )
    found = contradicted(review, FILES)
    assert [c.kind for c in found] == ["count", "not_read"]
    assert (
        found[0]
        .to_model()
        .startswith("You say 117 files in api/alembic/versions/, but the repository holds 2.")
    )
    said = contradictions_said(found)
    assert said.startswith("## Points contredits par le code")
    assert "« 117 fichiers dans `api/alembic/versions/` » : le dépôt en compte 2." in said
    assert contradictions_said(found, language="en").startswith("## Points the code contradicts")
    assert contradicted("Tout va bien.", FILES) == [] and contradicted(review, {}) == []


def test_a_file_said_not_read_with_its_risk_left_open_is_no_finding() -> None:
    # 2026-11-01: the regression and impact analyses name what they could
    # not read, its risk « inconnu », and list it under « Limites » — honest,
    # never said contradicted.
    review = "\n".join(
        [
            "## Risques de régression",
            "| Risque | Comportement | Où |",
            "|---|---|---|",
            "| inconnu | prix des offres | `api/leka/billing/catalogue.py` (non lu) |",
            "| élevé | **N+1 possible** | `api/leka/identity/repository.py` (non lu) |",
            "## Limites",
            "| Fichier | Domaine | Pourquoi |",
            "|---|---|---|",
            "| `api/leka/billing/catalogue.py` | facturation | non lu : diff coupé |",
        ]
    )
    found = contradicted(review, FILES)
    assert [(c.kind, "identity/repository.py" in c.said) for c in found] == [("not_read", True)]


NIGHT = """\"\"\"The night review.

Only what is there: no model asked.
\"\"\"

import asyncio

UNREAD = 24


def checked(source):
    if source.last_synced_at is None:
        return "unread"


def standing(review):
    return review.points
"""


def test_a_line_cited_for_a_name_it_does_not_hold_is_contradicted_with_where() -> None:
    # 2026-11-01, a documentation of the night review: `standing` cited at
    # lines that are imports, `last_synced_at` twenty lines away. Three
    # lines either side still count as the line cited.
    files = {"api/leka/monitoring/night.py": NIGHT}
    doc = "\n".join(
        [
            "## Pages proposées",
            "Le filtre `standing` (`api/leka/monitoring/night.py:6-7`) retire les points réglés.",
            "La date `last_synced_at` (`night.py:3`) décide d'une source non lue.",
            # Right, or two lines off: it holds.
            "La fonction `checked` (`night.py:11`) et `standing` (`night.py:17`) lisent tout.",
            # No name in code beside it, or a name the file never holds: no claim.
            "Aucun modèle n'est appelé (`night.py:3`) ; tout est `déterministe` (`night.py:9`).",
        ]
    )
    found = contradicted(doc, files)
    assert [(c.kind, c.said, c.line, c.evidence) for c in found] == [
        ("line", "api/leka/monitoring/night.py:6-7", 16, "standing"),
        ("line", "night.py:3", 12, "last_synced_at"),
    ]
    assert (
        found[0]
        .to_model()
        .startswith(
            "You cite api/leka/monitoring/night.py:6-7 for `standing`, but those lines do not "
            "hold it: `standing` is at api/leka/monitoring/night.py:16."
        )
    )
    assert "ces lignes ne contiennent pas `standing`, qui est en" in contradictions_said(found)


COOKIES = """def set_session_cookie(response, token):
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
    )


def set_csrf_cookie(response):
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
    )
"""


def test_a_line_misplaced_is_said_where_the_very_code_cited_is() -> None:
    # 2026-11-01, a security review: `httponly=False` cited off, and the line
    # given was the session cookie's `httponly=True`; « X-CSRF-Token » sent
    # LEKA looking for the word « CSRF » in a docstring.
    files = {"api/leka/identity/cookies.py": COOKIES}
    doc = "\n".join(
        [
            "## Surface",
            "Le jeton CSRF est lisible (`httponly=False`, `cookies.py:4`).",
            "Il est tiré par `secrets.token_urlsafe(32)` (`cookies.py:4`).",
            "Le cookie `settings.session_cookie_name` (`cookies.py:16`) porte la session.",
            # A header's name is no code to look for, nor a plain word.
            "L'en-tête `X-CSRF-Token` (`cookies.py:1`) est comparé.",
        ]
    )
    found = contradicted(doc, files)
    assert [(c.said, c.line, c.evidence) for c in found] == [
        ("cookies.py:4", 14, "httponly=False"),
        ("cookies.py:4", 10, "secrets.token_urlsafe(32)"),
        ("cookies.py:16", 3, "settings.session_cookie_name"),
    ]


def test_a_command_calling_a_host_no_file_knows_is_contradicted() -> None:
    files = {
        "docs/deployment.md": "The API answers at https://api.leka-core.com.\n",
        "api/leka/main.py": "app = FastAPI()\n",
    }
    doc = "\n".join(
        [
            "## Procédure",
            "Le site public https://inconnu.example.org n'est pas une commande.",
            "```bash",
            'curl -X POST "https://api.leka.halimi.net/api/v1/monitoring/night-review"',
            'curl "https://api.leka-core.com/api/v1/health"',
            'curl "http://localhost:8000/api/v1/health" "https://api.example.com/x"',
            "```",
        ]
    )
    found = contradicted(doc, files)
    assert [(c.kind, c.said) for c in found] == [("host", "api.leka.halimi.net")]
    assert "no file of the repository knows the host api.leka.halimi.net" in found[0].to_model()
    assert "aucun fichier du dépôt ne connaît cette adresse" in contradictions_said(found)


def test_a_database_leka_does_not_read_is_unknown_never_empty() -> None:
    unread = library.schema_of([], database="LEKA", engine=None)
    unread.connected, unread.known_from = False, ["github"]
    [signal] = library.judge_schema(unread)
    assert signal.code == "schema.not_connected"
    assert "unknown here, not missing" in signal.text and "github" in signal.text
    # Connected, and still nothing: empty, said so.
    assert [
        s.code for s in library.judge_schema(library.schema_of([], database="x", engine=None))
    ] == ["schema.empty"]


@pytest.mark.integration
async def test_an_agent_told_what_the_code_contradicts_corrects_it_or_the_reader_is_told(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    github: Any,
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runs_module, "settings", settings.model_copy(update={"agent_corrections": 2})
    )
    # Its sections are another check's: here, the code alone.
    monkeypatch.setattr(runs_module, "missing", lambda *args, **kwargs: [])
    github.listed["app/models.py"] = MODELS
    await _github_source(acme["acme"])
    await sync_catalogue()
    _as(identity, acme, "member")
    wrong = (
        "## Résumé\nÀ risque.\n## Index et requêtes\n"
        "- `accounts.owner_id` n'a aucun index (`app/models.py:4`).\n"
        "## Plan d'action\n1. L'ajouter."
    )
    right = (
        "## Résumé\nSaine.\n## Index et requêtes\n"
        "- `accounts.owner_id` est indexé (`app/models.py:4`).\n## Plan d'action\n1. Rien."
    )
    read = gemini(call={"name": "read_file", "args": {"repository": REPO, "path": "app/models.py"}})
    script = leka_gemini(read, gemini(wrong), gemini(right))

    async def review() -> dict[str, Any]:
        started = await client.post(
            RUNS,
            json={"key": "database-review", "inputs": {"base": "accounts", "depot": REPO}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["id"]
        assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}
        found: dict[str, Any] = (await client.get(f"{RUNS}/{run_id}")).json()
        return found

    done = await review()
    told = script.asked[2]["contents"][-1]["parts"][0]["text"]
    assert "You say accounts.owner_id has no index, but app/models.py:4 has" in told
    assert done["output"] == right

    # It insists: delivered, the reader told what the code contradicts, in
    # the run's language.
    leka_gemini(read, gemini(wrong), gemini(wrong), gemini(wrong))
    done = await review()
    assert done["output"].startswith(wrong)
    assert "## Points the code contradicts" in done["output"]
    assert "`accounts.owner_id`: `app/models.py:4` already declares the index" in done["output"]
    assert "contradicted" in [e["kind"] for e in done["events"]]
