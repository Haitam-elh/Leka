"""What an agent's deliverable must hold, checked whatever model wrote it
(2026-10-22: « whatever the model, the same deliverable — or better »).

Each agent says, in its « Ce qu'il produit », the sections of its deliverable:
`1. **Verdict** — …`, `2. **Ce qui était attendu** — …`. A section that says
when it applies — « seulement s'il est ouvert », « quand des données réelles
ont été essayées », « dès que la demande est de proposer » — may be left out;
every other one is expected.

    sections()   the sections an agent's instructions expect, and which may
                 be left out
    missing()    those its deliverable lacks — said to the model, which
                 writes it again (gateway.run_tools' judge)

A deliverable in French is read section by section, by the words of each
title; in another language, by how many sections it has: the titles are
translated, never their number.

Framed (Karim, 2026-10-23: « pas que du texte d'analyse — un résumé et un
plan d'action concret et exécutable »): every markdown deliverable opens on
« Résumé » and ends on « Plan d'action » (runtime.FRAME_NOTE) — an agent's
own « Actions » section is that plan.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Where an agent says what it produces, and how it numbers its sections.
_PRODUCES = re.compile(r"^## Ce qu.il produit\s*$(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_SECTION = re.compile(r"^(\d+)\.\s+\*\*(.+?)\*\*\s*(?:\u2014|\u2013|-|:)?\s*(.*)$", re.MULTILINE)
# How a section says it applies only sometimes.
_WHEN = re.compile(
    r"^(?:seulement|uniquement|quand|lorsque|dès que|si |s'il|pour une application|"
    r"le cas échéant|au besoin|only|when|if )",
    re.IGNORECASE,
)
# The lines of a deliverable that open a section: a heading, a bold line, a
# numbered bold line.
_OPENS = re.compile(r"^\s*(?:#{1,6}\s+.+|\*\*.+\*\*.*|\d+\.\s+\*\*.+\*\*.*)$", re.MULTILINE)
# Words that do not tell one section from another.
_SMALL = frozenset(
    {
        "le", "la", "les", "l", "un", "une", "des", "de", "du", "d", "et", "ou", "en", "a",
        "au", "aux", "ce", "qui", "que", "quoi", "il", "elle", "est", "ete", "sa", "son",
        "ses", "sur", "par", "pour", "dans", "avec", "ne", "pas", "the", "of", "and", "to",
    }
)  # fmt: skip
# Of a deliverable in another language, the share of its sections expected.
SHARE = 0.6


@dataclass(frozen=True)
class Section:
    title: str
    optional: bool


# What frames every markdown deliverable (2026-10-23).
SUMMARY = Section("Résumé", optional=False)
PLAN = Section("Plan d'action", optional=False)


def _plain(text: str) -> list[str]:
    flat = unicodedata.normalize("NFKD", text.lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", flat)


def sections(instructions: str) -> list[Section]:
    """The sections an agent's instructions expect of its deliverable — its
    first numbered list in « Ce qu'il produit »; none when it lists none."""
    found = _PRODUCES.search(instructions or "")
    if found is None:
        return []
    said: list[Section] = []
    for number, title, rest in _SECTION.findall(found.group(1)):
        if int(number) != len(said) + 1:
            break
        said.append(Section(title.strip(), bool(_WHEN.match(rest.strip()))))
    return said


def _covers(title: str, line: str) -> bool:
    wanted = [w for w in _plain(title) if w not in _SMALL] or _plain(title)
    have = set(_plain(line))
    return sum(w in have for w in wanted) * 2 >= len(wanted)


def expected(instructions: str, *, framed: bool = False) -> list[Section]:
    """The sections a deliverable must hold: its agent's — opened by the
    summary and closed by the action plan when framed, its own actions
    becoming that plan."""
    own = [s for s in sections(instructions) if not s.optional]
    if not framed:
        return own
    kept = [s for s in own if not {"action", "actions", "resume"} & set(_plain(s.title))]
    return [SUMMARY, *kept, PLAN]


def missing(
    instructions: str, deliverable: str, *, language: str = "fr", framed: bool = False
) -> list[str]:
    """What the deliverable lacks of what its agent expects — said to the
    model that wrote it; nothing when it holds every section."""
    expected_ = expected(instructions, framed=framed)
    if not expected_:
        return []
    opened = _OPENS.findall(deliverable or "")
    if not language.lower().startswith("fr"):
        wanted = math.ceil(len(expected_) * SHARE)
        if len(opened) >= wanted:
            return []
        return [
            f"The deliverable has {len(opened)} of the {len(expected_)} sections its agent "
            f"must give: {', '.join(s.title for s in expected_)} — each under its own title."
        ]
    lacking = [s.title for s in expected_ if not any(_covers(s.title, line) for line in opened)]
    if not lacking:
        return []
    return [
        "The deliverable lacks these sections, each to write under its own title: "
        + ", ".join(f"« {t} »" for t in lacking)
        + ". A section with nothing to say says so in one line."
    ]


# A file and its line, as a deliverable cites them: `api/app/main.py:42`.
_CODE = (
    "py|ts|tsx|js|jsx|mjs|cjs|go|rb|java|kt|kts|scala|cs|php|rs|swift|sql|sh|tf|"
    "yaml|yml|json|toml|ini|cfg|md|txt|lock|css|scss|less|html|vue|svelte|prisma|proto|graphql"
)
_CITED_LINE = re.compile(
    rf"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:{_CODE})):(\d+)(?:[-\u2013](\d+))?\b"
)


def unread(deliverable: str, files: Mapping[str, str]) -> list[str]:
    """The lines a deliverable cites in files the agent never read, or past
    their end (2026-10-23: `intentions.py:250`, `errors.py:100` — lines no
    one read) — said to the model, which reads them or cites the file
    alone. `files`: what it read, « owner/repo:path » → its text."""
    lines = {key.split(":", 1)[-1]: text.count("\n") + 1 for key, text in files.items()}
    wrong: list[str] = []
    for path, first, last in _CITED_LINE.findall(deliverable or ""):
        read = next((n for p, n in lines.items() if p == path or p.endswith(f"/{path}")), None)
        line = int(last or first)
        if read is None:
            wrong.append(f"{path}:{first} (never read)")
        elif line > read:
            wrong.append(f"{path}:{line} (it has {read} lines)")
    if not wrong:
        return []
    said = ", ".join(dict.fromkeys(wrong))
    return [
        f"These lines are cited but were not read: {said}. Read each file (read_file) and "
        "cite the line you read, or cite the file alone — never a line you did not read."
    ]


# A repository's full name, as a request writes it: owner/repo.
_REPOSITORY = re.compile(r"(?<![\w./-])([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)(?![\w/-])")


def elsewhere(
    asked: str, files: Mapping[str, str], listed: Mapping[str, Sequence[str]]
) -> list[str]:
    """Code read in another repository than the one asked (2026-10-28:
    asked how acme/frontend is organised, Mistral read and described
    acme/backend). `asked`: the request — its `depot`, or the full names it
    writes that share an owner with what was read (a path is no repository)."""
    read = {key.split(":", 1)[0] for key in files} | set(listed)
    if not read:
        return []
    owners = {name.split("/", 1)[0] for name in read}
    named = [
        n for n in dict.fromkeys(_REPOSITORY.findall(asked or "")) if n.split("/")[0] in owners
    ]
    if not named or any(n in read for n in named):
        return []
    return [
        f"You were asked about {named[0]} and read {', '.join(sorted(read))}: read "
        f"{named[0]} (list_files, read_file) and answer about it."
    ]


# A sentence said this many times over is a model caught in a loop.
LOOPING = 4


def repeats(deliverable: str) -> list[str]:
    """A deliverable that says the same sentence again and again — a model
    caught in a loop (2026-10-28: « Je vais lister les fichiers dans
    `public`. », ten times, delivered) — said to the model."""
    # Prose only: a field of a list (« - **Qui** : Équipe backend. »), a
    # title, a table row repeat by design.
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\n+", deliverable or "")
        if len(s.strip()) >= 30 and not re.match(r"[-*#|>\d]", s.strip())
    ]
    counts: dict[str, int] = {}
    for sentence in sentences:
        counts[sentence] = counts.get(sentence, 0) + 1
    looped = [s for s, n in counts.items() if n >= LOOPING]
    if not looped:
        return []
    return [
        f"The answer says the same thing again and again (« {looped[0][:120]} »): stop, "
        "do what it announces with the tools, then write the deliverable once, from what you "
        "read — never a sentence repeated."
    ]


# A file a deliverable names, quoted as code: `app/main.py`, `web/a.tsx:12`.
_NAMED_FILE = re.compile(rf"`((?:[\w.@-]+/)*[\w.@-]+\.(?:{_CODE}))(?::\d+(?:[-\u2013]\d+)?)?`")


# What a line says of a file it names without having seen it: missing, an
# example, one to create — no invention (2026-10-28: « Aucune spécification
# (`openapi.json`) n'a été trouvée », « Créer un `docs/rollback.md` »).
_NOT_CLAIMED = re.compile(
    r"\b(?:ex\.|exemple|e\.g\.|for example|such as|aucune?|pas de|pas d'|absente?s?|introuvables?|"
    r"manqu\w*|n'existe|inexistant\w*|cré\w+|ajout\w*|nouv\w+|new|create\w*|add\w*|missing|"
    r"not found|no such|équivalent|equivalent|générée?s?|generated|à prévoir)",
    re.IGNORECASE,
)


def invented(
    deliverable: str,
    files: Mapping[str, str],
    listed: Mapping[str, Sequence[str]],
    pulls: Mapping[str, Mapping[str, object]],
    *,
    reads_code: bool,
) -> list[str]:
    """An agent that reads code and read none, or files a deliverable names
    that it neither read nor saw listed — said to the model (2026-10-28:
    Mistral, asked how acme/frontend is organised, read no file and
    described `app/main.py`, `requirements.txt`, none of them there).
    `files`: « owner/repo:path » → text; `listed`: repository → the paths
    list_files gave; `pulls`: the pull requests read, each with its files."""
    known = {key.split(":", 1)[-1] for key in files}
    known |= {path for paths in listed.values() for path in paths}
    for pull in pulls.values():
        changed = pull.get("files")
        if isinstance(changed, list):
            known |= {str(f.get("path") or "") for f in changed if isinstance(f, dict)}
    if not known and reads_code:
        return [
            "No file of the repository was read: list its files (list_files), read those "
            "the answer rests on (read_file), then answer from what you read — never "
            "describe code you did not read."
        ]

    def seen(path: str) -> bool:
        return any(k == path or k.endswith(f"/{path}") or path.endswith(f"/{k}") for k in known)

    unseen: list[str] = []
    for line in (deliverable or "").splitlines():
        # Its words, not the paths it quotes: `new.ts` says nothing.
        if _NOT_CLAIMED.search(re.sub(r"`[^`]*`", "", line)):
            continue
        unseen += [p for p in _NAMED_FILE.findall(line) if not seen(p) and p not in unseen]
    if not unseen:
        return []
    return [
        "These files are named but were neither read nor listed, and may not exist: "
        + ", ".join(unseen[:12])
        + ". Name only files list_files showed or read_file read; check the others first."
    ]


# A design implemented by halves: what of it an analysis puts off — « une
# étape suivante », « dans un second temps », « a follow-up ».
_DEFERRED = re.compile(
    r"(?:(?:étape|etape|phase|itération|iteration|pull request|PR|lot|passe)s?\s+"
    r"(?:suivantes?|ultérieures?|ulterieures?|prochaines?|future|à venir))"
    r"|(?:prochaine|seconde|deuxième|deuxieme)\s+(?:étape|etape|phase|pull request|PR|passe)"
    r"|dans un (?:second|deuxième|deuxieme) temps|ultérieurement|ulterieurement"
    r"|réservée?s? (?:pour|à) (?:une|la|plus)|reportée?s? (?:à|a|pour)"
    r"|(?:a |the )?(?:later|next|follow-up|future) (?:step|phase|pull request|PR|iteration|pass)"
    r"|in a (?:second|follow-up) (?:step|pass|pull request)",
    re.IGNORECASE,
)


def deferred(deliverable: str) -> list[str]:
    """What of a design to implement an analysis puts off (2026-10-24: asked
    to implement the chosen direction, the change did four classes and left
    the rest « for a later step ») — said to the model, which does it all."""
    found = _DEFERRED.search(deliverable or "")
    if found is None:
        return []
    return [
        f"Part of the design to implement is put off (« {found.group(0)} »). The whole chosen "
        "direction is asked now: change every file its mock-up changes, until the screen in "
        "the code looks like the mock-up; read a cut file to its end (read_file with "
        "from_line). Nothing of it is left for a later step."
    ]


# ── what a deliverable says, held to the code (2026-10-31) ────────────────
#
# A database review, written by a mid-range model, listed « critical missing
# indexes » the repository creates, « 117 migrations » where there are 102,
# and an N+1 in a file it marked « not read ». Its instructions already said
# « before you say something is missing, look for it »: a rule a model may
# skip, so LEKA looks itself, in the repository's files, and says back what
# contradicts the deliverable — the model corrects it; what still stands
# after is said to the reader.

# Words that say something is not there.
_ABSENT = re.compile(
    r"manquant|missing|absent|aucun index|sans index|pas d.index|non index|unindexed|"
    r"no index|without (?:an )?index",
    re.IGNORECASE,
)
_ABOUT_INDEX = re.compile(r"index", re.IGNORECASE)
# Where a claim is not one: what could not be checked, what is to measure.
_HEDGED = re.compile(
    r"pas pu .tre v.rifi|not (?:been )?verified|could not be|. mesurer|to measure|questions?|"
    r"limites?\b|limits?\b|non lus?\b|not read|unread|angles? morts?|blind spots?",
    re.IGNORECASE,
)
# A file said not read, its risk honestly left open (2026-11-01: the
# regression and impact analyses keep « inconnu » for code they could not
# read): no finding made on it.
_LEFT_OPEN = re.compile(
    r"\binconnue?s?\b|\bunknown\b|non jug|not judged|. lire\b|to read\b|non .valu|not assessed",
    re.IGNORECASE,
)
_TICKED = re.compile(r"`([^`\n]{1,160})`")
_PAIR = re.compile(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b")
_ON = re.compile(r"\bON\s+([\w.\"]+)\s*\(([^)]*)\)", re.IGNORECASE)
_INDEX_NAME = re.compile(r"\b((?:ix|idx|index)_[\w]+)\b", re.IGNORECASE)
# How code declares an index, in the usual tools: Alembic, SQLAlchemy's
# models, SQL, Rails. What it does not say for sure — a name computed, a
# column object — is left out: never said indexed on a guess.
_SQL_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:\"?([\w.]+)\"?\s+)?ON\s+(?:ONLY\s+)?\"?([\w.]+)\"?\s*(?:USING\s+\w+\s*)?\(\s*\"?(\w+)",
    re.IGNORECASE,
)
_SQL_DROP_INDEX = re.compile(
    r"DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?\"?([\w.]+)", re.IGNORECASE
)
_RAILS_INDEX = re.compile(r"add_index\s*\(?\s*[:\"'](\w+)[\"']?\s*,\s*\[?\s*[:\"'](\w+)")
_ALEMBIC_INDEX = re.compile(r"\b(create_index|create_unique_constraint|create_primary_key)\(")
_ALEMBIC_DROP_INDEX = re.compile(r"\bdrop_index\(")
_INDEXY = re.compile(r"index|__tablename__|create_table|constraint", re.IGNORECASE)
_DOCUMENTS = (".md", ".mdx", ".rst", ".txt", ".adoc", ".html")
_TABLENAME = re.compile(r"__tablename__\s*=\s*[\"'](\w+)[\"']")
_ATTRIBUTE = re.compile(
    r"^[ \t]+(\w+)\s*(?::[^=\n]*)?=\s*(?:\w+\.)?(?:mapped_column|Column)\(", re.MULTILINE
)
_CONSTRAINT = re.compile(r"\b(?:\w+\.)?(Index|UniqueConstraint|PrimaryKeyConstraint)\(")
_KEYED = re.compile(r"\b(?:index|unique|primary_key)\s*=\s*True")
_COUNTED = re.compile(
    r"\b(\d{1,5})\s+(?:fichiers?|files?|migrations?(?:\s+alembic)?)\b[^\n|]{0,60}?"
    r"`([\w@.-]+(?:/[\w@.-]+)+/?)`",
    re.IGNORECASE,
)
_NOT_READ = re.compile(r"\bnon lu\b|\bnot read\b|\bpas lu\b", re.IGNORECASE)
# How a migration makes a table and its columns: Alembic's own words, and
# the SQL it may run. A table renamed is left alone: its columns came from
# another name.
_CREATE_TABLE = re.compile(r"create_table\(\s*[\"'](\w+)[\"']")
_ADD_COLUMN = re.compile(r"add_column\(")
_QUOTED = re.compile(r"[\"'][^\"']*[\"']")
_QUOTED_NAME = re.compile(r"[\"'](\w+)[\"']")
_NAMED_CALL = re.compile(r"[\w.]+\(\s*[\"'](\w+)[\"']")
_NOT_A_COLUMN = re.compile(r"[\w.]*(?:Constraint|Index)\(|\w+\s*=[^=]")
_ALTERS = re.compile(r"(alter_column|rename_table)\(")
_RENAMED = re.compile(r"rename_table\(|new_column_name\s*=|RENAME\s+(?:TO|COLUMN)", re.IGNORECASE)
MOST_CONTRADICTIONS = 6


@dataclass(frozen=True)
class Contradiction:
    """A point of a deliverable the code contradicts: what it says, and where
    the code says otherwise."""

    said: str
    kind: str  # index, column, count, not_read
    path: str = ""
    line: int = 0
    evidence: str = ""

    def to_model(self) -> str:
        if self.kind == "index":
            return (
                f"You say {self.said} has no index, but {self.path}:{self.line} has "
                f"`{self.evidence}`. Read it, then correct or remove that point: a missing "
                "index is said only once looked for, and where."
            )
        if self.kind == "column" and self.evidence == "dropped":
            return (
                f"You say {self.said} has no index, but that column no longer exists: "
                f"{self.path}:{self.line} drops it. Remove that point, or say what replaced it "
                "(search_code)."
            )
        if self.kind == "column":
            return (
                f"You say {self.said} has no index, but no migration of the repository makes "
                f"that column: the table is created at {self.path}:{self.line} without it, and "
                "no later migration adds it. Look for the column's real name (search_code), or "
                "remove that point."
            )
        if self.kind == "count":
            return (
                f"You say {self.line} files in {self.said}, but the repository holds "
                f"{self.evidence}. Count again (list_files), or say the number you read."
            )
        return (
            f"« {self.said} »: a finding on a file you did not read is no finding. Read the "
            "file (read_file), or move the point to « Ce qui n'a pas pu être vérifié »."
        )


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _bare(name: str) -> str:
    return name.strip().strip('"`[]').split(".")[-1].lower()


def _index_claims(line: str) -> list[tuple[str, str, set[str]]]:
    """The (table, column) a line says lacks an index — and the names of the
    index it proposes."""
    names = {n.lower() for n in _INDEX_NAME.findall(line)}
    pairs: list[tuple[str, str]] = []
    for code in _TICKED.findall(line):
        on = _ON.search(code)
        if on:
            columns = [c.strip() for c in on.group(2).split(",") if c.strip()]
            if columns:
                pairs.append((_bare(on.group(1)), _bare(columns[0].split()[0])))
            continue
        for table, column in _PAIR.findall(code):
            pairs.append((table.lower(), column.lower()))
    if not pairs and line.strip().startswith("|"):
        # A table's row: its first two cells in code, the table then the
        # column (« | `memberships` | `user_id` | Clé étrangère | … »).
        ticked = [_TICKED.findall(c) for c in _cells(line)]
        firsts = [t[0] for t in ticked if t][:2]
        if len(firsts) == 2:
            pairs.append((_bare(firsts[0]), _bare(firsts[1])))
    return [(t, c, names) for t, c in dict.fromkeys(pairs)]


@dataclass(frozen=True)
class _Index:
    """An index the code declares: its table, the column it starts with —
    the one it serves alone — its name, and where."""

    table: str
    column: str
    name: str
    path: str
    line: int
    text: str
    # A model's: the schema as it is today, never dropped since.
    model: bool = False


def _literal(argument: str) -> str | None:
    """A quoted name, or Alembic's `op.f("…")` around one."""
    made = re.fullmatch(r"(?:\w+\.f\()?\s*[\"'](\w+)[\"']\s*\)?", argument.strip())
    return made.group(1).lower() if made else None


def _first_listed(argument: str) -> str | None:
    """The first name of a list of columns (`["user_id", …]`)."""
    made = re.match(r"[\[(]\s*[\"'](\w+)[\"']", argument.strip())
    return made.group(1).lower() if made else None


def _line_of(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def _said(call: str) -> str:
    return " ".join(call.split())[:200]


def _indexes_of(files: Mapping[str, str]) -> list[_Index]:
    """Every index the repository's files declare, and still keep: one a
    migration drops by its name is gone."""
    made: list[_Index] = []
    dropped: list[str] = []
    for path, written in files.items():
        if path.lower().endswith(_DOCUMENTS) or not _INDEXY.search(written):
            continue
        python = path.endswith(".py")
        text = _upgrade_of(_code_of(written)) if python else written
        for one in _SQL_INDEX.finditer(text):
            name, table, column = (g.lower() if g else "" for g in one.groups())
            line = _line_of(text, one.start())
            made.append(_Index(_bare(table), column, _bare(name), path, line, _said(one.group(0))))
        dropped += [_bare(d) for d in _SQL_DROP_INDEX.findall(text)]
        for one in _RAILS_INDEX.finditer(text):
            table, column = one.group(1).lower(), one.group(2).lower()
            line = _line_of(text, one.start())
            made.append(_Index(table, column, "", path, line, _said(text.split("\n")[line - 1])))
        if not python:
            continue
        for one in _ALEMBIC_INDEX.finditer(text):
            call = _balanced(text, one.end() - 1)
            arguments = _arguments(call)
            if len(arguments) < 3:
                continue
            name, table = _literal(arguments[0]), _literal(arguments[1])
            column = _first_listed(arguments[2])
            if table and column:
                line = _line_of(text, one.start())
                written_as = text[text.rfind("\n", 0, one.start()) + 1 : one.end() - 1] + call
                made.append(_Index(table, column, name or "", path, line, _said(written_as)))
        for one in _ALEMBIC_DROP_INDEX.finditer(text):
            arguments = _arguments(_balanced(text, one.end() - 1))
            name = _literal(arguments[0]) if arguments else None
            if name:
                dropped.append(name)
        for one in _CREATE_TABLE.finditer(text):
            table = one.group(1).lower()
            call = _balanced(text, text.index("(", one.start()))
            start = text.index("(", one.start())
            for argument in _arguments(call)[1:]:
                at = start + call.find(argument)
                column = _keyed(argument)
                if column:
                    line = _line_of(text, at)
                    made.append(_Index(table, column, "", path, line, _said(argument)))
        for one in _TABLENAME.finditer(text):
            # A model: its class, from its `class` line to the next one.
            begin = text.rfind("\nclass ", 0, one.start()) + 1
            end = text.find("\nclass ", one.end())
            block = text[begin : len(text) if end < 0 else end]
            table = one.group(1).lower()
            for attribute in _ATTRIBUTE.finditer(block):
                call = _balanced(block, attribute.end() - 1)
                if _KEYED.search(" ".join(_arguments(call))):
                    named = _arguments(call)
                    column = (_literal(named[0]) if named else None) or attribute.group(1).lower()
                    line = _line_of(text, begin + attribute.start())
                    said = _said(attribute.group(0) + call[1:])
                    made.append(_Index(table, column, "", path, line, said, model=True))
            for constraint in _CONSTRAINT.finditer(block):
                arguments = _arguments(_balanced(block, constraint.end() - 1))
                names = [a for a in (_literal(x) for x in arguments) if a]
                index = constraint.group(1) == "Index"
                if index and len(names) >= 2 and _literal(arguments[0]) and _literal(arguments[1]):
                    name, column = names[0], names[1]
                elif not index and names and _literal(arguments[0]):
                    name, column = "", names[0]
                else:
                    continue
                line = _line_of(text, begin + constraint.start())
                said = _said(text.split("\n")[line - 1])
                made.append(_Index(table, column, name, path, line, said, model=True))
    created = Counter(i.name for i in made if i.name and not i.model)
    gone = {name for name, times in Counter(dropped).items() if times >= created.get(name, 0)}
    return [i for i in made if i.model or i.name not in gone]


def _keyed(argument: str) -> str | None:
    """The column a `Column("x", …, index=True)` of a `create_table` makes
    an index on — or a key's first column."""
    if re.match(r"(?:\w+\.)?Column\(", argument) and _KEYED.search(argument):
        named = _NAMED_CALL.match(argument)
        return named.group(1).lower() if named else None
    key = re.match(r"(?:\w+\.)?(?:UniqueConstraint|PrimaryKeyConstraint)\(\s*[\"'](\w+)", argument)
    return key.group(1).lower() if key else None


def _indexed(
    table: str, column: str, names: set[str], indexes: Sequence[_Index]
) -> tuple[str, int, str] | None:
    """Where the code declares an index starting with that column of that
    table — or creates, on that table, the very index proposed."""
    for one in indexes:
        if one.table == table and (one.column == column or (one.name and one.name in names)):
            return one.path, one.line, one.text
    return None


def _balanced(text: str, start: int) -> str:
    """The call opened at `start` — up to its closing parenthesis, strings
    skipped."""
    depth, quote, n = 0, "", start
    while n < len(text):
        char = text[n]
        if quote:
            if char == "\\":
                n += 1
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : n + 1]
        n += 1
    return text[start:]


# Python's strings — triple-quoted first — and its comments.
_PY_TOKEN = re.compile(
    r'"""[\s\S]*?"""'
    r"|'''[\s\S]*?'''"
    r'|"(?:\\.|[^"\\\n])*"'
    r"|'(?:\\.|[^'\\\n])*'"
    r"|#[^\n]*"
)


def _code_of(text: str) -> str:
    """Python's text without its comments — a comment's apostrophe is no
    string — lines kept, so their numbers hold."""
    return _PY_TOKEN.sub(
        lambda m: " " * len(m.group(0)) if m.group(0)[0] == "#" else m.group(0), text
    )


def _arguments(call: str) -> list[str]:
    """A call's arguments `(…)` as written, split at its own commas."""
    found: list[str] = []
    depth, quote, start = 0, "", 1
    for n, char in enumerate(call):
        if quote:
            if char == quote and call[n - 1] != "\\":
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                found.append(call[start:n])
                break
        elif char == "," and depth == 1:
            found.append(call[start:n])
            start = n + 1
    return [a.strip() for a in found if a.strip()]


def _named(argument: str) -> str | None:
    """The column an argument makes, by its name in quotes — `sa.Column("x",
    …)` or a helper's `_jsonb("x")`; "" for what is no column (a constraint,
    an option); None when it makes one out of sight (`*timestamps()`, a
    name computed)."""
    made = _NAMED_CALL.match(argument)
    if made:
        return made.group(1).lower()
    if _NOT_A_COLUMN.match(argument):
        return ""
    return None


@dataclass(frozen=True)
class _Table:
    """What a repository's migrations make of a table: where they create
    it, every column it may have, and those dropped since — with where."""

    path: str
    line: int
    columns: frozenset[str]
    dropped: dict[str, tuple[str, int]]


def _upgrade_of(text: str) -> str:
    """A migration's way forward: its `downgrade()` puts back what it
    removed, and is no column of today."""
    back = text.find("\ndef downgrade")
    return text if back < 0 else text[:back]


def _columns_of(table: str, files: Mapping[str, str]) -> _Table | None:
    """Where the migrations create that table, and every column they give
    it — then or later. None when no migration creates it, or it is renamed,
    or a column is made out of sight: then the code says nothing for sure."""
    created: tuple[str, int] | None = None
    columns: set[str] = set()
    added: set[str] = set()
    dropped: dict[str, tuple[str, int]] = {}
    quoted = re.compile(rf"[\"']{re.escape(table)}[\"']", re.IGNORECASE)
    batch = re.compile(rf"batch_alter_table\(\s*[\"']{re.escape(table)}[\"']", re.IGNORECASE)
    altered = re.compile(
        rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?{re.escape(table)}\"?\s+ADD\s+"
        r"(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(\S+)",
        re.IGNORECASE,
    )
    removed = re.compile(
        rf"drop_column\(\s*[\"']{re.escape(table)}[\"']\s*,\s*[\"'](\w+)[\"']", re.IGNORECASE
    )
    for path, written in files.items():
        if not quoted.search(written) and table not in written.lower():
            continue
        text = _upgrade_of(_code_of(written)) if path.endswith(".py") else written
        batched = bool(batch.search(text))
        # A name computed (`for column in (…)`): any name the file quotes
        # may be it.
        loose = {c.lower() for c in _QUOTED_NAME.findall(text)}
        for made in _CREATE_TABLE.finditer(text):
            if made.group(1).lower() != table:
                continue
            created = created or (path, text.count("\n", 0, made.start()) + 1)
            for argument in _arguments(_balanced(text, text.index("(", made.start())))[1:]:
                name = _named(argument)
                if name is None:
                    return None
                columns.add(name)
        for add in _ADD_COLUMN.finditer(text):
            arguments = _arguments(_balanced(text, add.end() - 1))
            if arguments and _QUOTED.fullmatch(arguments[0]):
                if not quoted.fullmatch(arguments[0]):
                    continue  # another table's
                arguments = arguments[1:]
            elif not batched:
                continue
            name = _named(arguments[0]) if arguments else None
            added |= {name} if name else loose
        for sql in altered.findall(text):
            name = sql.strip("\"'`;,")
            added |= {name.lower()} if re.fullmatch(r"\w+", name) else loose
        for drop in removed.finditer(text):
            dropped[drop.group(1).lower()] = (path, text.count("\n", 0, drop.start()) + 1)
        for alter in _ALTERS.finditer(text):
            body = _balanced(text, alter.end() - 1)
            if quoted.search(body) and (alter.group(1) == "rename_table" or _RENAMED.search(body)):
                return None
        for line in text.split("\n"):
            if quoted.search(line) and _RENAMED.search(line):
                return None
        if batched and _RENAMED.search(text):
            return None
    columns.discard("")
    if created is None or not columns:
        return None
    # Dropped, then added again — in whatever order: it may be there.
    gone = {c: where for c, where in dropped.items() if c not in added}
    return _Table(created[0], created[1], frozenset((columns | added) - set(gone)), gone)


def contradicted(deliverable: str, files: Mapping[str, str]) -> list[Contradiction]:
    """What the deliverable says that the repository's files contradict: an
    index said missing that the code declares, or on a column no migration
    makes; a count of files that is not the count; a finding on a file said
    not read. `files`: path → text."""
    if not deliverable or not files:
        return []
    found: list[Contradiction] = []
    seen: set[tuple[str, str]] = set()
    indexes: list[_Index] | None = None
    heading = ""
    for raw in deliverable.split("\n"):
        line = raw.strip()
        if line.startswith("#"):
            heading = line
            continue
        if not line or _HEDGED.search(heading):
            continue
        absent = bool(_ABSENT.search(line)) or bool(
            _ABSENT.search(heading) and line.startswith("|") and "`" in line
        )
        if absent and (_ABOUT_INDEX.search(line) or _ABOUT_INDEX.search(heading)):
            for table, column, names in _index_claims(line):
                if (table, column) in seen:
                    continue
                seen.add((table, column))
                made = _columns_of(table, files)
                if made is not None and column in made.dropped:
                    path, n = made.dropped[column]
                    found.append(Contradiction(f"{table}.{column}", "column", path, n, "dropped"))
                    continue
                indexes = _indexes_of(files) if indexes is None else indexes
                where = _indexed(table, column, names, indexes)
                if where is not None:
                    path, n, evidence = where
                    found.append(Contradiction(f"{table}.{column}", "index", path, n, evidence))
                elif made is not None and column not in made.columns:
                    found.append(Contradiction(f"{table}.{column}", "column", made.path, made.line))
        for number, folder in _COUNTED.findall(line):
            prefix = folder.strip("/") + "/"
            held = [
                p
                for p in files
                if p.startswith(prefix)
                and "/" not in p[len(prefix) :]
                and not p.rsplit("/", 1)[-1].startswith(("__", "."))
            ]
            if held and len(held) != int(number):
                found.append(
                    Contradiction(folder, "count", line=int(number), evidence=str(len(held)))
                )
        if _NOT_READ.search(line) and line.startswith("|") and not _LEFT_OPEN.search(line):
            found.append(Contradiction(line.strip("| ")[:160], "not_read"))
    return found[:MOST_CONTRADICTIONS]


def contradictions_said(found: Sequence[Contradiction], *, language: str = "fr") -> str:
    """What still contradicts the code once the agent was told, said to the
    reader at the end of the deliverable — never left as if it held."""
    if not found:
        return ""
    french = language.lower().startswith("fr")
    lines = [
        "## Points contredits par le code" if french else "## Points the code contradicts",
        "",
        (
            "LEKA a vérifié ces points dans le code du dépôt après la rédaction : ils sont "
            "contredits. Ne les suivez pas sans les relire."
            if french
            else "LEKA checked these points in the repository's code after they were written: "
            "the code contradicts them. Do not act on them without reading them again."
        ),
        "",
    ]
    for one in found:
        if one.kind == "index":
            lines.append(
                f"- `{one.said}` : `{one.path}:{one.line}` déclare déjà l'index (`{one.evidence}`)."
                if french
                else f"- `{one.said}`: `{one.path}:{one.line}` already declares the index "
                f"(`{one.evidence}`)."
            )
        elif one.kind == "column" and one.evidence == "dropped":
            lines.append(
                f"- `{one.said}` : cette colonne n'existe plus, `{one.path}:{one.line}` "
                "la supprime."
                if french
                else f"- `{one.said}`: that column no longer exists, `{one.path}:{one.line}` "
                "drops it."
            )
        elif one.kind == "column":
            lines.append(
                f"- `{one.said}` : cette colonne n'existe pas dans le code (la table est créée "
                f"en `{one.path}:{one.line}` sans elle, et aucune migration ne l'ajoute)."
                if french
                else f"- `{one.said}`: no such column in the code (the table is created at "
                f"`{one.path}:{one.line}` without it, and no migration adds it)."
            )
        elif one.kind == "count":
            lines.append(
                f"- « {one.line} fichiers dans `{one.said}` » : le dépôt en compte {one.evidence}."
                if french
                else f"- « {one.line} files in `{one.said}` »: the repository holds {one.evidence}."
            )
        else:
            lines.append(
                f"- « {one.said} » : le fichier n'a pas été lu."
                if french
                else f"- « {one.said} »: the file was not read."
            )
    return "\n".join(lines)


__all__ = [
    "PLAN",
    "SHARE",
    "SUMMARY",
    "Contradiction",
    "Section",
    "contradicted",
    "contradictions_said",
    "deferred",
    "elsewhere",
    "expected",
    "invented",
    "missing",
    "repeats",
    "sections",
    "unread",
]
