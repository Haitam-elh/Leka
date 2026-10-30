"""The code-change agent's workshop (2026-10-30): the agent makes its change
itself, edit by edit, in a draft LEKA keeps — never in the repository —
instead of describing it for another model to write in one answer.

Each edit is answered at once: where it landed, the lines around it with
their numbers, a file that no longer parses; one that does not land says
why and where the closest lines are. A large change is planned in steps
and done one step at a time, each checked; the whole draft is checked
before anyone sees it. LEKA then proposes the draft as it does any change:
its diff, before and after, for a person who decides.

    Draft           a branch as the agent changed it: each file's text on
                    the branch and in the draft, what each edit replaced
                    (undo), the plan of the change
    edit / insert / write / delete / undo
    search          a regular expression through every file of the branch
                    (its archive, read once), the draft's text where it
                    changed — or, the archive refused, the files read
    problems        what LEKA checks before a person sees it: a file that
                    no longer parses, a key written twice, a name, an import
                    or a variant that is nowhere, what a test reads taken away

Nothing reaches a repository before a person accepts the change.
"""

from __future__ import annotations

import asyncio
import difflib
import fnmatch
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.changes import (
    MAX_DRAFTED,
    RULE_FILES,
    ChangeProposal,
    Edit,
    Held,
    ProposedFile,
    apply_edits,
    broken,
    diff_of,
    held_names,
    lost_ids,
    safe_path,
    unimported,
    unknown_names,
    whole_problems,
)
from leka.capabilities.code_names import written_twice
from leka.capabilities.gateway import Gateway, Message, Needs, NoModelError, Request, Tier
from leka.connectors import CodeRefusedError, GitHubCode

logger = structlog.get_logger(__name__)

# Lines shown around an edit, each side.
AROUND = 4
# What a search gives back, at most: lines, lines of one file, one line.
MOST_MATCHES = 80
MOST_PER_FILE = 10
MOST_LINE = 240
# A search through the whole branch, at most this long.
SEARCH_SECONDS = 20.0
# Files a draft may change, at most (a change of more is split by a person).
MOST_DRAFTED = MAX_DRAFTED
# A diff shown to the agent, at most.
MOST_DIFF = 60_000
# The repository's rules given with a folder's first file, each at most.
MOST_RULES = 6_000
# Steps of a plan, at most; a step's words.
MOST_STEPS = 40
MOST_STEP = 300
STATUSES = ("todo", "doing", "done")
# A drafting agent's conversation, kept within this many characters: its
# oldest reads dropped first (gateway `condensed`), its draft kept whole.
DRAFT_CONTEXT = 400_000
# What the closest lines are said by, when a text is not found.
CLOSE_ENOUGH = 0.6
# Searches in a row that find nothing before the agent is told to stop
# looking (2026-10-30: Mistral searched 30 times for a class not there).
EMPTY_SEARCHES = 4


class EditError(Exception):
    """Why an edit did not land — said to the agent, which edits again."""


@dataclass
class Step:
    title: str
    status: str = "todo"
    note: str = ""

    def said(self) -> dict[str, str]:
        said = {"title": self.title, "status": self.status}
        return {**said, "note": self.note} if self.note else said


def numbered(text: str, first: int, last: int) -> str:
    """Lines `first` to `last` of a text (1-based), each with its number."""
    lines = text.split("\n")
    first = max(first, 1)
    last = min(last, len(lines))
    return "\n".join(f"{n:>6}\t{lines[n - 1]}" for n in range(first, last + 1))


def changed_lines(before: str, after: str) -> tuple[int, int]:
    """Where two texts differ, as lines of the second (1-based): the first
    and last line that changed — the place an edit landed."""
    old, new = before.split("\n"), after.split("\n")
    start = 0
    while start < min(len(old), len(new)) and old[start] == new[start]:
        start += 1
    end_old, end_new = len(old), len(new)
    while end_old > start and end_new > start and old[end_old - 1] == new[end_new - 1]:
        end_old -= 1
        end_new -= 1
    return start + 1, max(end_new, start + 1)


def lines_holding(text: str, wanted: str) -> list[int]:
    """The lines (1-based) where each occurrence of a text starts."""
    lines: list[int] = []
    at = text.find(wanted)
    while at >= 0:
        lines.append(text.count("\n", 0, at) + 1)
        at = text.find(wanted, at + 1)
    return lines


def closest(text: str, wanted: str) -> str:
    """Where a text not found is closest, said by its lines: what was meant,
    most likely — copied again from there, it lands."""
    lines = text.split("\n")
    asked = [line for line in wanted.strip("\n").split("\n") if line.strip()]
    if not asked or not lines:
        return ""
    first = asked[0].strip()
    stripped = [line.strip() for line in lines]
    candidates = difflib.get_close_matches(first, stripped, n=2, cutoff=CLOSE_ENOUGH)
    said: list[str] = []
    for candidate in candidates:
        at = stripped.index(candidate) + 1
        said.append(numbered(text, at, at + len(asked) - 1))
    if not said:
        return ""
    return "The closest lines in the file:\n" + "\n---\n".join(said)


@dataclass
class Draft:
    """A branch as the agent changed it, kept in LEKA — never written to
    the repository until a person accepts the change."""

    code: GitHubCode
    repository: str
    ref: str
    # Each file's text on the branch (None: not there), and in the draft
    # (None: deleted).
    before: dict[str, str | None] = field(default_factory=dict)
    now: dict[str, str | None] = field(default_factory=dict)
    history: dict[str, list[str | None]] = field(default_factory=dict)
    plan: list[Step] = field(default_factory=list)
    # The branch's files, read once to search them; why not, when refused.
    archive: dict[str, str] | None = None
    archive_refused: str | None = None
    tree: list[str] | None = None
    rules_given: set[str] = field(default_factory=set)
    # What the files it changes may use (code_names), read once.
    held: Held | None = None
    # Files the agent read, as they are on the branch: what checks compare.
    read: dict[str, str] = field(default_factory=dict)
    edits: int = 0
    # Searches in a row that found nothing.
    misses: int = 0

    # ── reading ──────────────────────────────────────────────────────────

    def path_of(self, said: object) -> str:
        path = safe_path(re.sub(r"^[\w.-]+/[\w.-]+:", "", str(said or "").strip()))
        if path is None:
            raise EditError(f"« {said} » is not a path inside the repository.")
        return path

    async def base(self, path: str) -> str | None:
        """A file as it is on the branch, read once."""
        if path not in self.before:
            if self.archive is not None and path in self.archive:
                self.before[path] = self.archive[path]
            else:
                try:
                    self.before[path] = await self.code.read(self.repository, path, self.ref)
                except CodeRefusedError as refused:
                    if refused.code != "too_large":
                        raise EditError(f"{path} cannot be read: {refused}") from refused
                    self.before[path] = await self.code.read_whole(
                        self.repository, path, self.ref, most=5_000_000
                    )
        return self.before[path]

    async def text(self, path: str) -> str | None:
        """A file as the draft holds it now."""
        if path in self.now:
            return self.now[path]
        return await self.base(path)

    def changed(self) -> dict[str, tuple[str | None, str | None]]:
        """Each file the draft changes: its text before, and now."""
        return {
            path: (self.before.get(path), after)
            for path, after in self.now.items()
            if after != self.before.get(path)
        }

    async def paths(self) -> list[str]:
        """The branch's files, as the draft has them."""
        if self.archive is not None:
            listed = list(self.archive)
        else:
            if self.tree is None:
                try:
                    self.tree, _more = await self.code.paths(self.repository, self.ref)
                except CodeRefusedError:
                    self.tree = []
            listed = list(self.tree)
        listed += [p for p, t in self.now.items() if t is not None and p not in listed]
        return [p for p in listed if self.now.get(p, "") is not None]

    async def rules_for(self, path: str) -> str:
        """The repository's rules for whoever writes in this file's folders
        (AGENTS.md, CLAUDE.md…), from its root down — each folder's once:
        they travel with the code they rule."""
        folders = [""]
        parts = path.split("/")[:-1]
        folders += ["/".join(parts[: n + 1]) + "/" for n in range(len(parts))]
        present = set(await self.paths())
        said: list[str] = []
        for folder in folders:
            if folder in self.rules_given:
                continue
            self.rules_given.add(folder)
            for name in RULE_FILES:
                rule = f"{folder}{name}"
                if rule not in present:
                    continue
                try:
                    text = await self.base(rule)
                except EditError:
                    continue
                if text and text.strip():
                    said.append(f"## {rule}\n\n{text.strip()[:MOST_RULES]}")
        return "\n\n".join(said)

    # ── editing ──────────────────────────────────────────────────────────

    def _kept(self, path: str, before: str | None, after: str | None) -> None:
        if len(self.changed()) >= MOST_DRAFTED and path not in self.now:
            raise EditError(
                f"This change already holds {MOST_DRAFTED} files, the most one change may: "
                "finish it, and say the rest in « Ce qui n'est pas fait ici »."
            )
        self.history.setdefault(path, []).append(before)
        self.now[path] = after
        self.edits += 1

    async def _landed(self, path: str, before: str, after: str, said: str) -> str:
        """An edit, answered: where it landed, the lines around it, whether
        the file still holds together."""
        first, last = changed_lines(before, after)
        shown = numbered(after, first - AROUND, last + AROUND)
        warning = ""
        base = self.before.get(path)
        why = broken(path, base if base is not None else "", after)
        if why:
            warning = (
                f"\nWARNING: {path}: {why}. Fix it now: copy whole blocks, every bracket "
                "a block opens closed."
            )
        return (
            f"{said} {path}, lines {first}-{last} now:\n{shown}{warning}\n"
            "Check these lines; edit again if they are not as they must be."
        )

    async def replace(self, said_path: object, old: str, new: str, count: int = 1) -> str:
        """`old` replaced by `new` in a file: exactly where it is — `count`
        times, when it is there that many times — or, copied with other
        spaces or indentation, where its lines are, as the file indents."""
        path = self.path_of(said_path)
        text = await self.text(path)
        if text is None:
            raise EditError(f"{path} is not in the repository: create it with write_file.")
        if not old:
            raise EditError(
                "old_text is empty: copy the exact lines to replace (insert_lines adds lines, "
                "write_file writes a whole file)."
            )
        if old == new:
            raise EditError("old_text and new_text are the same: nothing would change.")
        found = text.count(old)
        if found > 1 or count > 1:
            if found != count:
                where = lines_holding(text, old)
                raise EditError(
                    f"old_text is in {path} {found} times (lines {where[:20]}), {count} "
                    "expected: copy more lines around the one you mean so it is there once — or "
                    f"give expected_replacements={found} to replace each."
                    if found
                    else f"old_text is not in {path}. {closest(text, old)}"
                )
            after = text.replace(old, new)
        else:
            landed, why = apply_edits(text, [Edit(find=old, replace=new)])
            if landed is None:
                if why == "ambiguous":
                    raise EditError(
                        f"old_text's lines are in {path} more than once once spaces are set "
                        "aside: copy more lines around the one you mean."
                    )
                hint = closest(text, old)
                raise EditError(
                    f"old_text is not in {path} as you wrote it: copy whole lines exactly as "
                    f"the file has them (read_file).{(' ' + hint) if hint else ''}"
                )
            after = landed
        self._kept(path, text, after)
        return await self._landed(path, text, after, "Edited")

    async def insert(self, said_path: object, after_line: object, lines: str) -> str:
        """Lines added after a line of a file (0: at its top)."""
        path = self.path_of(said_path)
        text = await self.text(path)
        if text is None:
            raise EditError(f"{path} is not in the repository: create it with write_file.")
        try:
            at = int(str(after_line))
        except ValueError as error:
            raise EditError("after_line must be a line number (0: at the top).") from error
        rows = text.split("\n")
        if at < 0 or at > len(rows):
            raise EditError(f"{path} has {len(rows)} lines: after_line goes from 0 to {len(rows)}.")
        added = lines.rstrip("\n").split("\n")
        after = "\n".join([*rows[:at], *added, *rows[at:]])
        self._kept(path, text, after)
        return await self._landed(path, text, after, "Inserted in")

    async def write(self, said_path: object, content: str) -> str:
        """A whole file: a new one, or one rewritten through most of its
        lines — every line of it, never « … » standing for code kept."""
        path = self.path_of(said_path)
        text = await self.text(path)
        if text is not None:
            cut = [p for p in whole_problems(path, text, content) if "stands for code" in p]
            if cut:
                raise EditError(cut[0])
        self._kept(path, text, content)
        if text is None:
            why = broken(path, "", content)
            warning = f"\nWARNING: {path}: {why}. Fix it now." if why else ""
            return (
                f"Created {path} ({content.count(chr(10)) + 1} lines).{warning}\n"
                "Read it again with read_file if you need to check it."
            )
        shorter = (
            f"\nNOTE: it is now {len(content)} characters where it had {len(text)}: "
            "make sure no line it must keep was left out."
            if text.strip() and len(content) < 0.4 * len(text)
            else ""
        )
        return (await self._landed(path, text, content, "Rewrote")) + shorter

    async def delete(self, said_path: object) -> str:
        path = self.path_of(said_path)
        text = await self.text(path)
        if text is None:
            raise EditError(f"{path} is not in the repository.")
        self._kept(path, text, None)
        return f"Deleted {path} from the draft. undo_edit gives it back."

    def undo(self, said_path: object) -> str:
        path = self.path_of(said_path)
        kept = self.history.get(path)
        if not kept:
            raise EditError(f"No edit of {path} to undo.")
        self.now[path] = kept.pop()
        if not kept and self.now[path] == self.before.get(path):
            self.now.pop(path, None)
        return f"Undid the last edit of {path}."

    # ── searching ────────────────────────────────────────────────────────

    async def everything(self) -> tuple[dict[str, str], str | None]:
        """Every text file of the branch as the draft holds it — or, its
        archive refused, the files read so far; and why, then."""
        if self.archive is None and self.archive_refused is None:
            try:
                self.archive = await self.code.archive(self.repository, self.ref)
            except CodeRefusedError as refused:
                self.archive_refused = refused.code
                logger.info("draft_archive_refused", repository=self.repository, code=refused.code)
        files: dict[str, str] = dict(self.archive or {})
        if self.archive is None:
            files |= {p: t for p, t in self.before.items() if t is not None}
            files |= self.read
        for path, text in self.now.items():
            if text is None:
                files.pop(path, None)
            else:
                files[path] = text
        return files, self.archive_refused

    async def search(
        self,
        pattern: str,
        *,
        include: str = "",
        under: str = "",
        literal: bool = False,
        ignore_case: bool = False,
    ) -> dict[str, Any]:
        """The lines that match a regular expression, file by file."""
        if not pattern:
            raise EditError("pattern is empty.")
        try:
            wanted = re.compile(
                re.escape(pattern) if literal else pattern, re.IGNORECASE if ignore_case else 0
            )
        except re.error as error:
            raise EditError(
                f"« {pattern} » is not a regular expression ({error}): escape what it means "
                "literally, or give literal=true."
            ) from error
        files, refused = await self.everything()
        prefix = under.strip("/")
        chosen = [
            p
            for p in sorted(files)
            if (not prefix or p == prefix or p.startswith(prefix + "/"))
            and (not include or matches_glob(p, include))
        ]

        def look() -> tuple[list[dict[str, object]], int, bool]:
            found: list[dict[str, object]] = []
            hit_files = 0
            more = False
            for path in chosen:
                mine = 0
                for n, line in enumerate(files[path].split("\n"), 1):
                    if not wanted.search(line):
                        continue
                    if mine == 0:
                        hit_files += 1
                    mine += 1
                    if mine > MOST_PER_FILE or len(found) >= MOST_MATCHES:
                        more = True
                        continue
                    found.append({"path": path, "line": n, "text": line.strip()[:MOST_LINE]})
            return found, hit_files, more

        try:
            found, hit_files, more = await asyncio.wait_for(
                asyncio.to_thread(look), timeout=SEARCH_SECONDS
            )
        except TimeoutError as error:
            raise EditError(
                "This search takes too long: give a simpler pattern, or narrow it with path or "
                "include."
            ) from error
        said: dict[str, Any] = {
            "pattern": pattern,
            "matches": found,
            "files_matched": hit_files,
            "searched": len(chosen),
            "more": more,
        }
        self.misses = 0 if found else self.misses + 1
        if self.misses >= EMPTY_SEARCHES:
            said["note"] = (
                f"Your last {self.misses} searches found nothing: what you look for is likely not "
                "in this repository as you imagine it. Work from what you found, or say what is "
                "missing in « Ce qui n'est pas fait ici »."
            )
        elif refused:
            said["note"] = (
                f"Only the {len(chosen)} files read so far were searched: the repository's "
                f"archive could not be read ({refused})."
            )
        elif more:
            said["note"] = "More lines match: narrow the search with path or include."
        return said

    # ── what it changes ──────────────────────────────────────────────────

    def diff(self, path: str | None = None) -> str:
        """The draft's diff — one file's, or all of it."""
        said: list[str] = []
        for name, (before, after) in sorted(self.changed().items()):
            if path and name != path:
                continue
            said.append(diff_of(name, before, after)[0])
        text = "".join(said)
        if len(text) > MOST_DIFF:
            return text[:MOST_DIFF] + "\n[… cut: show_changes with a path shows one file]"
        return text

    def given(self) -> dict[str, str]:
        """The files as they are on the branch: those read, those changed."""
        return self.read | {p: t for p, t in self.before.items() if t is not None}

    async def problems(self) -> list[str]:
        """What would stop this change, as LEKA checks it before anyone sees
        it — each said where it is."""
        changed = self.changed()
        if not changed:
            return []
        given = self.given()
        after = {p: (t or "") for p, (_b, t) in changed.items()}
        said: list[str] = []
        for path, (before, now) in changed.items():
            if now is None:
                continue
            why = broken(path, before if before is not None else "", now)
            if why:
                said.append(f"{path}: {why}.")
            said += written_twice(before or "", now, path)
        said += lost_ids(given, after)
        said += unknown_names(given, {p: t for p, t in after.items() if p in given})
        said += unimported(given, after)
        if self.held is None:
            try:
                self.held = await held_names(
                    self.code,
                    self.repository,
                    self.ref,
                    {f"{self.repository}:{p}": t for p, t in given.items()},
                )
            except Exception:
                logger.warning("draft_names_not_read", exc_info=True)
                self.held = Held()
        new = [p for p, (before, _now) in changed.items() if before is None]
        said += self.held.problems({p: t for p, t in after.items() if t}, new)
        return list(dict.fromkeys(said))

    def plan_left(self) -> list[Step]:
        return [step for step in self.plan if step.status != "done"]

    def set_plan(self, steps: Sequence[Mapping[str, Any]]) -> list[Step]:
        kept: list[Step] = []
        for each in list(steps)[:MOST_STEPS]:
            title = str(each.get("title") or "").strip()[:MOST_STEP]
            if not title:
                continue
            status = str(each.get("status") or "todo").strip().lower()
            status = {"in_progress": "doing", "completed": "done", "pending": "todo"}.get(
                status, status
            )
            kept.append(
                Step(
                    title,
                    status if status in STATUSES else "todo",
                    str(each.get("note") or "").strip()[:MOST_STEP],
                )
            )
        self.plan = kept
        return kept

    def proposal(self, *, title: str = "", summary: str = "") -> ChangeProposal:
        """The draft, as a change LEKA proposes: each file whole, as the
        draft holds it — or deleted."""
        files = [
            ProposedFile(path=path, delete=True)
            if after is None
            else ProposedFile(path=path, content=after)
            for path, (_before, after) in sorted(self.changed().items())
        ]
        return ChangeProposal(
            repository=self.repository,
            base_branch=self.ref,
            title=title,
            summary=summary,
            files=files,
        )


def matches_glob(path: str, pattern: str) -> bool:
    """A path against a glob as people write them: `*.tsx`, `web/**/*.ts`,
    `**/test_*.py`, `*.{ts,tsx}`."""
    patterns = [pattern]
    braced = re.fullmatch(r"(.*)\{([^{}]+)\}(.*)", pattern)
    if braced:
        patterns = [braced.group(1) + one + braced.group(3) for one in braced.group(2).split(",")]
    for each in patterns:
        if "/" not in each:
            if fnmatch.fnmatch(path.rsplit("/", 1)[-1], each):
                return True
            continue
        if fnmatch.fnmatch(path, each) or (
            each.startswith("**/") and fnmatch.fnmatch(path, each[3:])
        ):
            return True
    return False


def plan_said(steps: Sequence[Step]) -> dict[str, Any]:
    done = sum(1 for s in steps if s.status == "done")
    return {
        "steps": [s.said() for s in steps],
        "done": done,
        "left": len(steps) - done,
    }


async def judged(draft: Draft | None) -> list[str]:
    """What the agent is told before its analysis is taken, its draft not
    done: what LEKA's checks find, the steps of its plan left (2026-10-30:
    a change is finished when it holds together, not when it is said done)."""
    if draft is None or not draft.changed():
        return []
    said: list[str] = []
    problems = await draft.problems()
    if problems:
        said.append(
            "Your draft still has these problems: "
            + " ".join(problems[:12])
            + " Fix them in the draft (edit_file, write_file), check with check_changes, then "
            "give your analysis again."
        )
    left = draft.plan_left()
    if left:
        said.append(
            "Your plan still has steps not done: "
            + "; ".join(f"« {s.title} » ({s.status})" for s in left[:10])
            + ". Do them in the draft and mark them done with plan — or, when one cannot be "
            "done here, say why in « Ce qui n'est pas fait ici » and mark it done."
        )
    return said


EXPERT_RULES = """You are the expert a coding agent asks for a second opinion \
on a change it makes to a company's code. Answer its question directly: a \
concrete recommendation it can follow, the risks, and what to check. You are \
shown its draft's diff so far. Never write the whole change, never call a \
tool. Answer in the language of the question. Never write the em dash « — »."""
# What the expert is given of the draft, at most.
MOST_EXPERT_DIFF = 20_000
MOST_EXPERT_CONTEXT = 30_000


async def expert_advice(
    session: AsyncSession,
    workspace_id: Any,
    question: str,
    context: str,
    draft: Draft | None,
) -> str:
    """A stronger model's advice on a hard point (ask_expert): the
    strongest the workspace may use answers — the same one, given the
    question alone, when there is none stronger."""
    material = f"Question:\n{question.strip()}\n"
    if context.strip():
        material += f"\nContext:\n{context.strip()[:MOST_EXPERT_CONTEXT]}\n"
    if draft is not None and draft.changed():
        material += f"\nThe draft's diff so far:\n{draft.diff()[:MOST_EXPERT_DIFF]}\n"
    if draft is not None and draft.plan:
        material += "\nIts plan:\n" + "\n".join(f"- [{s.status}] {s.title}" for s in draft.plan)
    request = Request(
        purpose="agent:code-change:expert",
        messages=[Message.system(EXPERT_RULES), Message.user(material)],
        tier=Tier.DEEP,
        max_tokens=6000,
    )
    gateway = Gateway(session, workspace_id)
    for needs in (Needs(quality=3), Needs()):
        try:
            done = await gateway.complete(request, needs)
        except NoModelError as error:
            if error.reason == "none":
                continue
            break
        return done.text.strip()
    return "No expert could answer: go on with what you know, and say the doubt in « Les risques »."


def nearest_paths(wanted: str, paths: Sequence[str], most: int = 5) -> list[str]:
    """The files a path not found most likely means: the same name
    elsewhere, then the closest spellings (2026-10-30: `leka/x.py` asked
    where the repository has `api/leka/x.py`)."""
    name = wanted.rsplit("/", 1)[-1]
    under = [p for p in paths if p.endswith(f"/{wanted}")]
    same = sorted(
        (p for p in paths if p.rsplit("/", 1)[-1] == name),
        key=lambda p: -difflib.SequenceMatcher(None, wanted, p).ratio(),
    )
    close = difflib.get_close_matches(wanted, list(paths), n=most, cutoff=0.5)
    return list(dict.fromkeys([*under, *same, *close]))[:most]
