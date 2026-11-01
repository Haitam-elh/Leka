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
