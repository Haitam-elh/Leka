"""A pull request read: its CI before its diffs (2026-11-01).

The acceptance of PR #456 spent its rounds, and the model concluding read
each result cut short: the CI, last after 31 files of diff, never reached
it, and the verdict said « no CI ». What a reader cut short still has comes
first.
"""

from __future__ import annotations

import json

import httpx
from pydantic import SecretStr

from leka.connectors.github import GitHubConfig, GitHubConnector, GitHubCredentials
from leka.connectors.github.code import GitHubCode


def _code(handler: object) -> GitHubCode:
    return GitHubCode(
        GitHubConnector(
            GitHubConfig.model_validate({"organization": "acme"}),
            GitHubCredentials(token=SecretStr("github_pat_11ABCDEFG0123456789_testtokenvalue")),
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        )
    )


async def test_a_pull_request_read_gives_its_ci_before_its_diffs() -> None:
    def github(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls/456"):
            return httpx.Response(
                200, json={"number": 456, "title": "Revue de nuit", "head": {"sha": "abc"}}
            )
        if path.endswith("/pulls/456/files"):
            files = [{"filename": f"api/f{n}.py", "patch": "+x\n" * 400} for n in range(31)]
            return httpx.Response(200, json=files)
        if path.endswith("/commits/abc/check-runs"):
            run = {"name": "api", "status": "completed", "conclusion": "success"}
            return httpx.Response(200, json={"check_runs": [run]})
        if path.endswith("/commits/abc/status"):
            return httpx.Response(200, json={"statuses": []})
        return httpx.Response(404)

    pull = await _code(github).pull("acme/api", 456)
    said = json.dumps(pull)
    assert pull["checks"]["state"] == "success"  # type: ignore[index]
    assert said.index('"checks"') < said.index('"patch"') < 12_000


async def test_a_pull_request_in_red_gives_what_failed_from_its_log() -> None:
    """2026-11-06: the build fixer read « api failed » and guessed which test;
    the log named eight."""

    def github(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls/506"):
            return httpx.Response(200, json={"number": 506, "head": {"sha": "abc"}})
        if path.endswith("/pulls/506/files"):
            return httpx.Response(200, json=[{"filename": "api/stripe.py", "patch": "-a\n+b"}])
        if path.endswith("/commits/abc/check-runs"):
            runs = [
                {"id": 7, "name": "api", "status": "completed", "conclusion": "failure"},
                {"id": 8, "name": "web", "status": "completed", "conclusion": "success"},
                {"id": 9, "name": "e2e", "status": "completed", "conclusion": "skipped"},
            ]
            return httpx.Response(200, json={"check_runs": runs})
        if path.endswith("/commits/abc/status"):
            return httpx.Response(200, json={"statuses": []})
        if path.endswith("/check-runs/7/annotations"):
            return httpx.Response(200, json=[])
        if path.endswith("/actions/jobs/7/logs"):
            return httpx.Response(
                200,
                text="collecting\nFAILED tests/test_billing_stripe.py::test_stripes_form_encoding"
                " - AssertionError\n8 failed, 4638 passed\n",
            )
        return httpx.Response(404)

    pull = await _code(github).pull("acme/api", 506)
    checks = pull["checks"]
    assert (checks["passed"], checks["skipped"], checks["failed"]) == (1, 1, ["api"])  # type: ignore[index]
    failures = pull["failures"]
    assert [f["name"] for f in failures] == ["api"]  # type: ignore[attr-defined]
    assert "test_stripes_form_encoding" in failures[0]["log"]  # type: ignore[index]
    said = json.dumps(pull)
    assert said.index('"failures"') < said.index('"patch"')


async def test_a_pull_request_in_green_reads_no_log() -> None:
    asked: list[str] = []

    def github(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        path = request.url.path
        if path.endswith("/pulls/1"):
            return httpx.Response(200, json={"number": 1, "head": {"sha": "abc"}})
        if path.endswith("/pulls/1/files"):
            return httpx.Response(200, json=[])
        if path.endswith("/commits/abc/check-runs"):
            run = {"id": 7, "name": "api", "status": "completed", "conclusion": "success"}
            return httpx.Response(200, json={"check_runs": [run]})
        if path.endswith("/commits/abc/status"):
            return httpx.Response(200, json={"statuses": []})
        return httpx.Response(404)

    pull = await _code(github).pull("acme/api", 1)
    assert "failures" not in pull
    assert not any("/logs" in path for path in asked)
