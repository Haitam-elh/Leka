"""The known vulnerabilities of third-party packages, looked up in the
public OSV database (osv.dev) — free, no key (2026-10-22: the dependency
analysis).

A model's memory of advisories is neither whole nor current: one it
recalls may not exist, one published last week it cannot know. The
packages a lock file installs (lockfiles.py) are looked up here, by name
and exact version, and the model is given what the database answers —
each advisory's id, its aliases (CVE…), what it says, how severe its
publisher rates it, and the versions that fix it.

What leaves LEKA: the names and versions of packages from public
registries, nothing else — never the code, never a private package's name
(`Package.public`). `LEKA_ADVISORIES_URL` empty: nothing is looked up,
and the agent says the vulnerabilities were not checked.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from leka.connectors import PublicTransport

# One batch's queries at most (the API takes 1,000).
BATCH = 500
# The advisories read in full, at most, per lookup: the rest are named.
MOST_DETAILS = 80
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
# The tests' MockTransport, or the network — public addresses only.
TRANSPORT: httpx.AsyncBaseTransport | None = None
# The publisher's words for severity (GitHub's), LEKA's four.
SEVERITIES = {
    "critical": "critical",
    "high": "high",
    "moderate": "medium",
    "medium": "medium",
    "low": "low",
}
RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}

Key = tuple[str, str, str]  # ecosystem, name, version


class AdvisoriesUnavailableError(Exception):
    """The database could not be reached, or did not answer as it should."""


@dataclass(frozen=True)
class Advisory:
    id: str
    aliases: tuple[str, ...]
    summary: str
    # critical, high, medium or low — None when its publisher rates none.
    severity: str | None
    # The versions that fix it, for this package: none known when empty.
    fixed: tuple[str, ...]
    published: str | None

    @property
    def url(self) -> str:
        return f"https://osv.dev/vulnerability/{self.id}"

    def said(self) -> dict[str, object]:
        return {
            "id": self.id,
            "aliases": list(self.aliases),
            "summary": self.summary,
            "severity": self.severity,
            "fixed_in": list(self.fixed),
            "published": self.published,
            "url": self.url,
        }


def _same(ecosystem: str, a: str, b: str) -> bool:
    """PyPI's names compare normalized: Django, django, dj_ango…"""

    def norm(name: str) -> str:
        return name.lower().replace("_", "-").replace(".", "-") if ecosystem == "PyPI" else name

    return norm(a) == norm(b)


def _severity(found: dict[str, Any]) -> str | None:
    said = found.get("database_specific")
    if isinstance(said, dict):
        rated = str(said.get("severity") or "").lower()
        if rated in SEVERITIES:
            return SEVERITIES[rated]
    for affected in found.get("affected") or []:
        said = affected.get("ecosystem_specific") if isinstance(affected, dict) else None
        if isinstance(said, dict):
            rated = str(said.get("severity") or "").lower()
            if rated in SEVERITIES:
                return SEVERITIES[rated]
    return None


def _fixed(found: dict[str, Any], ecosystem: str, name: str) -> tuple[str, ...]:
    versions: list[str] = []
    for affected in found.get("affected") or []:
        if not isinstance(affected, dict):
            continue
        package = affected.get("package") or {}
        if package.get("ecosystem") != ecosystem or not _same(
            ecosystem, str(package.get("name") or ""), name
        ):
            continue
        for span in affected.get("ranges") or []:
            for event in span.get("events") or []:
                if isinstance(event, dict) and event.get("fixed"):
                    versions.append(str(event["fixed"]))
    return tuple(dict.fromkeys(versions))


def _client(url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=url.rstrip("/"),
        timeout=TIMEOUT,
        headers={"User-Agent": "LEKA"},
        transport=TRANSPORT or PublicTransport(),
        follow_redirects=False,
    )


async def lookup(packages: Iterable[Key], *, url: str) -> dict[Key, list[Advisory]]:
    """Each package's known advisories, the worst first — only the packages
    some advisory names. Raises AdvisoriesUnavailableError."""
    asked: list[Key] = list(dict.fromkeys(packages))
    if not asked:
        return {}
    ids: dict[Key, list[str]] = {}
    try:
        async with _client(url) as client:
            for start in range(0, len(asked), BATCH):
                chunk = asked[start : start + BATCH]
                answer = await client.post(
                    "/v1/querybatch",
                    json={
                        "queries": [
                            {"package": {"ecosystem": e, "name": n}, "version": v}
                            for e, n, v in chunk
                        ]
                    },
                )
                if answer.status_code != 200:
                    raise AdvisoriesUnavailableError(f"querybatch answered {answer.status_code}")
                results = answer.json().get("results") or []
                for key, result in zip(chunk, results, strict=False):
                    found = [str(v["id"]) for v in (result or {}).get("vulns") or [] if "id" in v]
                    if found:
                        ids[key] = found
            details = await _details(client, ids.values())
    except (httpx.HTTPError, ValueError) as error:
        raise AdvisoriesUnavailableError(str(error)) from error
    return {key: _advisories(key, found, details) for key, found in ids.items()}


async def _details(
    client: httpx.AsyncClient, found: Iterable[Sequence[str]]
) -> dict[str, dict[str, Any]]:
    wanted = list(dict.fromkeys(i for ids in found for i in ids))[:MOST_DETAILS]
    gate = asyncio.Semaphore(8)

    async def one(advisory: str) -> tuple[str, dict[str, Any] | None]:
        async with gate:
            answer = await client.get(f"/v1/vulns/{advisory}")
        return advisory, answer.json() if answer.status_code == 200 else None

    read = await asyncio.gather(*(one(a) for a in wanted))
    return {advisory: body for advisory, body in read if isinstance(body, dict)}


def _advisories(
    key: Key, found: Sequence[str], details: dict[str, dict[str, Any]]
) -> list[Advisory]:
    ecosystem, name, _ = key
    kept: list[Advisory] = []
    named: set[str] = set()
    # GitHub's first: the one with a severity, the others its aliases.
    for advisory in sorted(found, key=lambda i: (not i.startswith("GHSA-"), i)):
        if advisory in named:
            continue
        body = details.get(advisory) or {}
        aliases = tuple(str(a) for a in body.get("aliases") or [])
        named |= {advisory, *aliases}
        kept.append(
            Advisory(
                id=advisory,
                aliases=aliases,
                summary=str(body.get("summary") or body.get("details") or "")[:300],
                severity=_severity(body) if body else None,
                fixed=_fixed(body, ecosystem, name) if body else (),
                published=str(body["published"])[:10] if body.get("published") else None,
            )
        )
    return sorted(kept, key=lambda a: (RANK[a.severity], a.id))


__all__ = ["RANK", "AdvisoriesUnavailableError", "Advisory", "lookup"]
