"""Reading human-written text: what it points at, who it names, its shape.

Titles, descriptions, commit messages, comments — markdown or plain. What is
in a fenced code block is not read for references: `#1` in a snippet is not
an issue, `@Override` is not a person.

Confidence follows how the thing was written. "Fixes #41" says the change
closes it (0.95); a link to an issue is certain it is that issue (0.9); a
bare "#41" or "PAY-42" is very likely one (0.7) — "UTF-8" is not, and is
left out.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from leka.ingestion.parsing.contract import (
    MAX_EXCERPT,
    Evidence,
    Fact,
    FactType,
    Target,
    TextStructure,
)

FENCE = re.compile(
    r"^(?P<indent>\s*)(?:```|~~~)(?P<lang>[\w+#.-]*)[^\n]*\n.*?^\s*(?:```|~~~)\s*$", re.M | re.S
)
INLINE_CODE = re.compile(r"`[^`\n]+`")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$", re.M)
TASK = re.compile(r"^\s*[-*+]\s+\[(?P<done>[ xX])\]\s", re.M)
URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
WORD = re.compile(r"\w+")

CLOSING = re.compile(
    r"(?i:\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b)[:\s]+"
    r"(?P<ref>(?:[\w.-]+/[\w.-]+)?#\d+|[A-Z][A-Z0-9]{1,9}-\d+)\b"
)
ISSUE_NUMBER = re.compile(r"(?<![\w/&])(?P<repo>[\w.-]+/[\w.-]+)?#(?P<n>\d{1,7})\b")
MERGE_REQUEST = re.compile(r"(?<![\w/])(?P<repo>[\w.-]+/[\w.-]+)?!(?P<n>\d{1,7})\b")
TICKET_KEY = re.compile(r"(?<![\w-])(?P<key>[A-Z][A-Z0-9]{1,9}-\d{1,7})(?![\w-])")
# In a branch name the key is followed by its slug: feature/LEKA-12-retry.
BRANCH_KEY = re.compile(r"(?<![A-Za-z0-9])(?P<key>[A-Za-z][A-Za-z0-9]{1,9}-\d{1,7})(?!\d)")
MENTION = re.compile(r"(?<![\w@.])@(?P<handle>[A-Za-z0-9](?:[A-Za-z0-9._-]{0,38}[A-Za-z0-9])?)")

# Uppercase-dash-number words that are not ticket keys.
NOT_KEYS = frozenset(
    {"UTF", "SHA", "ISO", "RFC", "CVE", "GHSA", "COVID", "HTTP", "TLS", "SSL", "MD", "AES", "RSA"}
    # and, in branch names, the words before a version
    | {"RELEASE", "HOTFIX", "FEATURE", "FIX", "BUGFIX", "V", "RC", "BUMP", "DEPENDABOT"}
)
# @-words that are not people: decorators, npm scopes and the like are in
# code; these are the ones that appear in prose.
NOT_HANDLES = frozenset({"here", "channel", "everyone", "all", "latest", "types"})


def strip_code(text: str) -> str:
    """The text with its code blocks and inline code replaced by spaces."""
    text = FENCE.sub(lambda m: " " * len(m.group(0)), text)
    return INLINE_CODE.sub(lambda m: " " * len(m.group(0)), text)


def excerpt(text: str, start: int, end: int) -> str:
    """The words around [start, end), at most MAX_EXCERPT characters."""
    room = max(0, (MAX_EXCERPT - (end - start)) // 2)
    left, right = max(0, start - room), min(len(text), end + room)
    cut = " ".join(text[left:right].split())
    return ("…" if left > 0 else "") + cut[:MAX_EXCERPT] + ("…" if right < len(text) else "")


def structure(texts: list[tuple[str, str]]) -> TextStructure:
    """The shape of all these texts, together. Each is (field, text)."""
    words = tasks = done = links = blocks = 0
    headings: list[str] = []
    languages: list[str] = []
    for _field, text in texts:
        for fence in FENCE.finditer(text):
            blocks += 1
            if fence.group("lang"):
                languages.append(fence.group("lang").lower())
        prose = strip_code(text)
        words += len(WORD.findall(prose))
        headings += [m.group("text")[:200] for m in HEADING.finditer(prose)]
        found = TASK.findall(prose)
        tasks += len(found)
        done += sum(1 for mark in found if mark in "xX")
        links += len(URL.findall(prose))
    return TextStructure(
        words=words,
        headings=headings[:50],
        code_languages=sorted(set(languages)),
        code_blocks=blocks,
        tasks_total=tasks,
        tasks_done=done,
        links=links,
    )


def facts(field: str, text: str, *, system: str | None) -> list[Fact]:
    """What one text points at and who it names. `system` is the one the
    record comes from: a bare "#41" in a GitHub pull request is GitHub's."""
    prose = strip_code(text)
    out: list[Fact] = []
    closed: set[tuple[int, int]] = set()

    for match in CLOSING.finditer(prose):
        ref = match.group("ref")
        target = _ticket(ref) if "#" not in ref else _numbered(ref, "issue", system)
        if target is None:
            continue
        closed.add(match.span("ref"))
        out.append(_fact(FactType.REFERENCES, "closes", target, 0.95, field, prose, match.span()))

    for match in URL.finditer(prose):
        url = match.group(0).rstrip(".,;:!?")
        target = url_target(url)
        if target is not None:
            out.append(
                _fact(FactType.REFERENCES, "mentions", target, 0.9, field, prose, match.span())
            )
        else:
            host = urlsplit(url).hostname
            if host:
                link = Target(kind="url", key=url[:500], system=None)
                out.append(_fact(FactType.LINKS_TO, host, link, 1.0, field, prose, match.span()))
    # URLs are read once: their paths must not be read again as #n or KEY-n.
    prose = URL.sub(lambda m: " " * len(m.group(0)), prose)

    for match in ISSUE_NUMBER.finditer(prose):
        if match.span() in closed or _inside(match.span(), closed):
            continue
        target = _numbered(match.group(0), "issue", system)
        if target is not None:
            out.append(
                _fact(FactType.REFERENCES, "mentions", target, 0.7, field, prose, match.span())
            )
    if system == "gitlab":
        for match in MERGE_REQUEST.finditer(prose):
            key = match.group(0)
            target = Target(kind="pull_request", key=key, system="gitlab")
            out.append(
                _fact(FactType.REFERENCES, "mentions", target, 0.7, field, prose, match.span())
            )
    for match in TICKET_KEY.finditer(prose):
        if _inside(match.span("key"), closed):
            continue
        target = _ticket(match.group("key"))
        if target is not None:
            out.append(
                _fact(FactType.REFERENCES, "mentions", target, 0.7, field, prose, match.span())
            )

    for match in MENTION.finditer(prose):
        handle = match.group("handle")
        if handle.lower() in NOT_HANDLES:
            continue
        person = Target(kind="person", key=handle, system=system)
        out.append(_fact(FactType.MENTIONS, None, person, 0.8, field, prose, match.span()))
    return out


def ticket_in_branch(name: str) -> Target | None:
    """The ticket key a branch name carries: feature/leka-12-retry → LEKA-12."""
    for match in BRANCH_KEY.finditer(name):
        ticket = _ticket(match.group("key").upper())
        if ticket is not None:
            return ticket
    return None


# ── inside ───────────────────────────────────────────────────────────────────


def _fact(
    kind: FactType,
    value: str | None,
    target: Target,
    confidence: float,
    field: str,
    text: str,
    span: tuple[int, int],
) -> Fact:
    return Fact(
        type=kind,
        value=value,
        target=target,
        confidence=confidence,
        evidence=Evidence(field=field, excerpt=excerpt(text, *span)),
    )


def _inside(span: tuple[int, int], spans: set[tuple[int, int]]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in spans)


def _ticket(key: str) -> Target | None:
    project = key.split("-", 1)[0]
    if project in NOT_KEYS:
        return None
    return Target(kind="issue", key=key, system=None)


def _numbered(ref: str, kind: str, system: str | None) -> Target | None:
    """'#41' or 'acme/api#41' — an issue or a pull request of the record's
    own code host: on GitHub the two share their numbers."""
    if system not in {"github", "gitlab", "bitbucket"}:
        return None
    return Target(kind=kind, key=ref, system=system)


def url_target(url: str) -> Target | None:
    """A link to a work item LEKA knows the shape of — what a document's
    links are read for too (LEKA-366)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = [p for p in parts.path.split("/") if p]
    if host == "github.com" and len(path) >= 4:
        owner, repo, what, ident = path[:4]
        kinds = {"pull": "pull_request", "issues": "issue", "commit": "commit"}
        if what in kinds:
            key = ident if what == "commit" else f"{owner}/{repo}#{ident}"
            return Target(kind=kinds[what], key=key, system="github")
    if host.endswith("gitlab.com") and "-" in path:
        at = path.index("-")
        project, rest = "/".join(path[:at]), path[at + 1 :]
        marks = {"merge_requests": ("pull_request", "!"), "issues": ("issue", "#")}
        if len(rest) >= 2 and rest[0] in marks:
            kind, mark = marks[rest[0]]
            return Target(kind=kind, key=f"{project}{mark}{rest[1]}", system="gitlab")
        if len(rest) >= 2 and rest[0] == "commit":
            return Target(kind="commit", key=rest[1], system="gitlab")
    if host == "bitbucket.org" and len(path) >= 4 and path[2] in {"pull-requests", "issues"}:
        kind = "pull_request" if path[2] == "pull-requests" else "issue"
        return Target(kind=kind, key=f"{path[0]}/{path[1]}#{path[3]}", system="bitbucket")
    if host.endswith(".atlassian.net") and len(path) >= 2 and path[0] == "browse":
        ticket = _ticket(path[1])
        return Target(kind="issue", key=ticket.key, system="jira") if ticket else None
    return None
