"""A code review's deliverable (2026-10-14: « où est son livrable ? »): the
pull request as the agent read it, its comments on their lines.

What these protect:
- A unified diff's lines, by side: added or unchanged in the new file,
  removed or unchanged in the old.
- The agent's `leka-review` block, held to what it read:
  - a comment on a line the diff shows, or on a whole file, is kept;
  - one on a line the diff does not show, on a file it does not change, or
    of an unknown kind, is dropped and counted;
  - a pull request it did not read is no review at all.
  The report a person reads is the text without the block.
- End to end, on a GitHub stand-in: the review lists the repository's pull
  requests, reads the last one with its diff — read-only, nothing written —
  and its run answers the review: the pulls listed, the one reviewed with its
  files, the comments that hold.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from leka.capabilities import execute_run, review_of, sync_catalogue, without_block
from leka.capabilities.review import lines_of
from leka.connectors.base import Connector
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import Script, gemini, leka_gemini, queued  # noqa: F401
from tests.test_code_changes_api import _github_source
from tests.test_context_engine import model  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

# The repository the GitHub source of test_code_changes_api holds.
REPO = "acme/payments"
RUNS = "/api/v1/agent-runs"
PATCH = (
    "@@ -10,4 +10,5 @@ def balance(account):\n"
    "     total = account.total\n"
    "-    return total\n"
    "+    pending = account.pending\n"
    "+    return total - pending\n"
    "     # done\n"
)
PULL = {
    "number": 7,
    "title": "Déduire les paiements en attente",
    "state": "closed",
    "merged_at": "2026-10-14T08:09:00Z",
    "draft": False,
    "user": {"login": "nora"},
    "html_url": f"https://github.com/{REPO}/pull/7",
    "created_at": "2026-10-13T10:00:00Z",
    "updated_at": "2026-10-14T08:09:00Z",
    "body": "Le solde ignore les paiements en attente.",
    "base": {"ref": "main"},
    "head": {"ref": "fix/balance"},
    "additions": 2,
    "deletions": 1,
    "changed_files": 1,
}


def _block(comments: list[dict[str, Any]], number: int = 7) -> str:
    said = {"repository": REPO, "number": number, "verdict": "prudence", "comments": comments}
    return f"# Revue\n\nLe solde change.\n\n```leka-review\n{json.dumps(said)}\n```\n"


def _read() -> dict[str, dict[str, Any]]:
    return {
        f"{REPO}#7": {
            "repository": REPO,
            "number": 7,
            "files": [{"path": "app/balance.py", "patch": PATCH}],
        }
    }


# ── pure ─────────────────────────────────────────────────────────────────────


def test_a_diff_s_lines_by_side() -> None:
    said = lines_of(PATCH)
    assert said["new"] == {10, 11, 12, 13}
    assert said["old"] == {10, 11, 12}


def test_comments_hold_on_what_was_read_the_rest_dropped_and_counted() -> None:
    output = _block(
        [
            {
                "path": "app/balance.py",
                "line": 12,
                "kind": "issue",
                "severity": "eleve",
                "title": "Pending peut être nul",
                "comment": "account.pending vaut None [e1].",
            },
            {
                "path": "app/balance.py",
                "line": 11,
                "side": "old",
                "kind": "issue",
                "comment": "L'ancien retour ignorait l'attente.",
            },
            {"path": "app/balance.py", "line": None, "kind": "good", "comment": "Lisible."},
            {
                "path": "app/balance.py",
                "line": 13,
                "kind": "suggestion",
                "comment": "Nommer le résultat.",
                "suggestion": "available = total - pending",
            },
            # A line the diff does not show; a file it does not change; no words.
            {"path": "app/balance.py", "line": 99, "kind": "issue", "comment": "?"},
            {"path": "app/other.py", "line": 1, "kind": "issue", "comment": "?"},
            {"path": "app/balance.py", "line": 12, "kind": "issue", "comment": ""},
            {"path": "app/balance.py", "line": 12, "kind": "praise", "comment": "?"},
        ]
    )
    review = review_of(output, _read())
    assert review is not None
    assert (review["repository"], review["number"], review["verdict"]) == (REPO, 7, "prudence")
    assert [(c["line"], c["side"], c["kind"]) for c in review["comments"]] == [
        (12, "new", "issue"),
        (11, "old", "issue"),
        (None, "new", "good"),
        (13, "new", "suggestion"),
    ]
    assert review["comments"][0]["severity"] == "eleve"
    # A severity is an issue's.
    assert review["comments"][3]["severity"] is None
    assert review["comments"][3]["suggestion"] == "available = total - pending"
    assert review["dropped"] == 4
    # What a person reads: the report, without the block.
    assert without_block(output) == "# Revue\n\nLe solde change."


def test_no_review_without_a_block_or_of_a_pull_it_did_not_read() -> None:
    assert review_of("# Revue\n\nRien.", _read()) is None
    assert review_of(_block([], number=8), _read()) is None
    assert review_of("```leka-review\nnot json\n```", _read()) is None


# ── end to end ───────────────────────────────────────────────────────────────


class GitHub:
    """GitHub's REST API as the review reads it — nothing may be written."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.asked.append((request.method, path))
        base = f"/repos/{REPO}"
        if request.method != "GET":
            return httpx.Response(405, json={"message": "read only"})
        if path == f"{base}/pulls":
            other = {**PULL, "number": 6, "title": "Autre", "merged_at": None, "state": "open"}
            return httpx.Response(200, json=[PULL, other])
        if path == f"{base}/pulls/7":
            return httpx.Response(200, json=PULL)
        if path == f"{base}/pulls/7/files":
            return httpx.Response(
                200,
                json=[
                    {
                        "filename": "app/balance.py",
                        "status": "modified",
                        "additions": 2,
                        "deletions": 1,
                        "patch": PATCH,
                    }
                ],
            )
        return httpx.Response(404, json={"message": f"unexpected {path}"})


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> GitHub:
    fake = GitHub()

    def http(
        self: Connector[Any, Any], base_url: str, headers: dict[str, str] | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url, headers=headers or {}, transport=httpx.MockTransport(fake)
        )

    monkeypatch.setattr(Connector, "http", http)
    return fake


async def test_the_review_reads_the_last_pull_and_its_run_answers_its_comments(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    github: GitHub,
) -> None:
    _as(identity, acme, "member")
    await _github_source(acme["acme"])
    await sync_catalogue()
    report = _block(
        [
            {
                "path": "app/balance.py",
                "line": 12,
                "kind": "issue",
                "severity": "moyen",
                "title": "Pending peut être nul",
                "comment": "account.pending vaut None.",
            },
            {"path": "app/balance.py", "line": 99, "kind": "issue", "comment": "hors diff"},
        ]
    )
    script = leka_gemini(
        gemini(call={"name": "list_pull_requests", "args": {"repository": REPO}}),
        gemini(call={"name": "read_pull_request", "args": {"repository": REPO, "number": 7}}),
        gemini(report),
    )
    started = await client.post(
        RUNS, json={"key": "code-review", "inputs": {"changement": f"la dernière PR de {REPO}"}}
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert await execute_run(acme["acme"], uuid.UUID(run_id)) == {"status": "succeeded"}

    assert {"list_pull_requests", "read_pull_request"} <= set(script.declared())
    # Read only.
    assert {method for method, _ in github.asked} == {"GET"}

    run = (await client.get(f"{RUNS}/{run_id}")).json()
    assert run["report"] == "# Revue\n\nLe solde change."
    review = run["review"]
    assert (review["repository"], review["number"], review["verdict"]) == (REPO, 7, "prudence")
    assert [p["number"] for p in review["pulls"]] == [7, 6]
    assert review["pull"]["merged"] is True and review["pull"]["author"] == "nora"
    [file] = review["pull"]["files"]
    assert (file["path"], file["additions"], file["deletions"]) == ("app/balance.py", 2, 1)
    assert "+    return total - pending" in file["patch"]
    assert [(c["line"], c["kind"], c["severity"]) for c in review["comments"]] == [
        (12, "issue", "moyen")
    ]
    assert review["dropped"] == 1
    assert "reviewed" in [e["kind"] for e in run["events"]]
