"""A code review's deliverable (2026-10-14): what the agent said, on the lines
it read. The code review reads a pull request's diff (read_pull_request,
code_tools.py). Its report ends with a `leka-review` block:

    ```leka-review
    {"repository": "owner/repo", "number": 273, "verdict": "prudence",
     "comments": [{"path": "api/x.py", "line": 42, "side": "new",
                   "kind": "issue", "severity": "eleve",
                   "title": "…", "comment": "…", "suggestion": "…"}]}
    ```

Here, pure, the block is read and held to what was read:
- the pull request must be one the agent read;
- each comment must name one of its files, and a line that file's diff has
  on that side. A file-level comment has no line.

What does not hold is dropped and counted, never shown. The screen draws
the pull request as the agent read it, its comments on their lines: red
for what is wrong, green for what to do better, or what is right.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

BLOCK = re.compile(r"```leka-review\s*\n(.*?)\n```", re.DOTALL)
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

KINDS = ("issue", "suggestion", "good")
SEVERITIES = ("critique", "eleve", "moyen", "faible")
VERDICTS = ("favorable", "prudence", "a_revoir")
SIDES = ("new", "old")
# What a comment may say, at most.
TITLE, COMMENT, SUGGESTION = 200, 2_000, 4_000
MOST_COMMENTS = 60


def lines_of(patch: str) -> dict[str, set[int]]:
    """The lines a unified diff shows, by side: `new` — added or unchanged,
    numbered in the new file; `old` — removed or unchanged, in the old."""
    found: dict[str, set[int]] = {"new": set(), "old": set()}
    old = new = 0
    for line in patch.splitlines():
        hunk = HUNK.match(line)
        if hunk:
            old, new = int(hunk.group(1)), int(hunk.group(2))
            continue
        if not old and not new:
            continue
        if line.startswith("+"):
            found["new"].add(new)
            new += 1
        elif line.startswith("-"):
            found["old"].add(old)
            old += 1
        elif line.startswith("\\"):
            continue
        else:
            found["new"].add(new)
            found["old"].add(old)
            old += 1
            new += 1
    return found


def without_block(output: str) -> str:
    """The report a person reads: the block is for the screen."""
    return BLOCK.sub("", output).rstrip()


def _text(value: object, most: int) -> str:
    return str(value or "").strip()[:most]


def review_of(output: str | None, pulls: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    """The review the screen draws, from the agent's block and the pull
    requests it read — None when it wrote none, or reviewed none it read."""
    if not output:
        return None
    found = BLOCK.search(output)
    if found is None:
        return None
    try:
        said = json.loads(found.group(1))
    except ValueError:
        return None
    if not isinstance(said, dict):
        return None
    repository = str(said.get("repository") or "").strip()
    try:
        number = int(said.get("number") or 0)
    except (TypeError, ValueError):
        return None
    pull = pulls.get(f"{repository}#{number}")
    if pull is None:
        return None
    files = {str(f.get("path")): f for f in pull.get("files") or [] if isinstance(f, dict)}
    shown = {path: lines_of(str(f.get("patch") or "")) for path, f in files.items()}
    comments: list[dict[str, Any]] = []
    dropped = 0
    for each in said.get("comments") or []:
        if not isinstance(each, dict) or len(comments) >= MOST_COMMENTS:
            dropped += 1
            continue
        path = str(each.get("path") or "").strip()
        kind = str(each.get("kind") or "issue")
        side = str(each.get("side") or "new")
        comment = _text(each.get("comment"), COMMENT)
        if path not in files or kind not in KINDS or side not in SIDES or not comment:
            dropped += 1
            continue
        line: int | None
        try:
            line = int(each["line"]) if each.get("line") is not None else None
        except (TypeError, ValueError):
            dropped += 1
            continue
        if line is not None and line not in shown[path][side]:
            # A line the diff does not show: not on what was read.
            dropped += 1
            continue
        severity = str(each.get("severity") or "")
        comments.append(
            {
                "path": path,
                "line": line,
                "side": side,
                "kind": kind,
                "severity": severity if kind == "issue" and severity in SEVERITIES else None,
                "title": _text(each.get("title"), TITLE),
                "comment": comment,
                "suggestion": _text(each.get("suggestion"), SUGGESTION) or None,
            }
        )
    verdict = str(said.get("verdict") or "")
    return {
        "repository": repository,
        "number": number,
        "verdict": verdict if verdict in VERDICTS else None,
        "comments": comments,
        "dropped": dropped,
    }
