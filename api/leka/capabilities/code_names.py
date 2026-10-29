"""What the files a change touches may use (2026-10-29): the names the
modules they import hold — what each exports, the variants its components
take — given to the writer, and the change held to them.

A weaker model writes `<Button variant="primary">` where the button knows
`default` and `outline`, imports `@/components/ui/fancy-card` that no file
is: the code does not build, the CI is red. What a repository map gives a
coding assistant (aider's, among others), said here in a few lines a
module, read with the code LEKA reads: no parser, the import lines and
the export lines as JavaScript and TypeScript write them.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Collection, Mapping, Sequence

# `import X, { A, B as C } from "…"`, `import type { T } from "…"`, `import "…"`.
_IMPORT = re.compile(
    r"""^\s*import\s+(?:type\s+)?(?:([\w$*{}\s,]+?)\s+from\s+)?["']([^"']+)["']""", re.M
)
_EXPORTED = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?"
    r"(?:function\*?|const|let|var|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)",
    re.M,
)
_EXPORTED_LIST = re.compile(r"^\s*export\s+(?:type\s+)?\{([^}]*)\}", re.M)
_SCRIPTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_TRIED = ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js", "/index.jsx")
# A JSX element and its attributes: `<Button variant="outline" size="sm"`.
_ELEMENT = re.compile(r"<([A-Z][\w$]*)((?:\s+[\w-]+(?:=(?:\"[^\"]*\"|'[^']*'|\{[^{}]*\}))?)*)")
_ATTRIBUTE = re.compile(r"""([\w-]+)=["']([^"']*)["']""")
MOST_IMPORTED = 15
MOST_SAID = 700


def is_script(path: str) -> bool:
    return path.endswith(_SCRIPTS)


def imports_of(text: str) -> list[tuple[list[str], str]]:
    """Each import: the names it binds, and where from."""
    found: list[tuple[list[str], str]] = []
    for match in _IMPORT.finditer(text):
        bound = match.group(1) or ""
        names = [
            part.split(" as ")[-1].strip()
            for part in re.split(r"[{},]", bound)
            if part.strip() and part.strip() != "*" and not part.strip().startswith("* as")
        ]
        found.append((names, match.group(2)))
    return found


def resolved(spec: str, importer: str, tree: Collection[str]) -> str | None:
    """The repository's file `spec` names, imported by `importer` — None
    for a package, or a file no listing holds. `@/` and `~/` are the
    importer's top folder, or its `src/`."""
    if spec.startswith("."):
        bases = [posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))]
    elif spec.startswith(("@/", "~/")):
        top = importer.split("/")[0] if "/" in importer else ""
        rest = spec[2:]
        bases = [f"{top}/{rest}", f"{top}/src/{rest}", rest] if top else [rest, f"src/{rest}"]
    else:
        return None
    for base in bases:
        for tail in _TRIED:
            if f"{base}{tail}" in tree:
                return f"{base}{tail}"
    return None


def is_local(spec: str) -> bool:
    return spec.startswith((".", "@/", "~/"))


def _keys(block: str) -> list[str]:
    """The keys of an object literal's top level: `{ a: …, "b-c": … }`."""
    keys: list[str] = []
    depth = 0
    token = ""
    quote = ""
    for char in block:
        if quote:
            token += char
            if char == quote:
                quote = ""
            continue
        if char in "\"'`":
            quote = char
            token += char
            continue
        if char in "{[(":
            depth += 1
            token = ""
            continue
        if char in "}])":
            depth -= 1
            token = ""
            continue
        if depth == 0 and char == ":":
            key = token.strip().strip("\"'`")
            if re.fullmatch(r"[\w$-]+", key):
                keys.append(key)
            token = ""
            continue
        if depth == 0 and char == ",":
            token = ""
            continue
        token += char
    return keys


def _object_after(text: str, at: int) -> str | None:
    """The object literal opening at or after `at`, its braces left out."""
    start = text.find("{", at)
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return None


def variants_of(text: str) -> dict[str, list[str]]:
    """The variants a module's components take, as `cva` declares them:
    `variants: { variant: { default, outline }, size: { sm, lg } }`."""
    found: dict[str, list[str]] = {}
    for match in re.finditer(r"\bvariants\s*:", text):
        block = _object_after(text, match.end())
        if block is None:
            continue
        for group in _keys(block):
            inner = re.search(rf"(?:^|[\s,{{]){re.escape(group)}\s*:", block)
            values = _object_after(block, inner.end()) if inner else None
            if values is not None:
                found.setdefault(group, [])
                found[group] += [v for v in _keys(values) if v not in found[group]]
    return found


def exported(text: str) -> list[str]:
    names = _EXPORTED.findall(text)
    for listed in _EXPORTED_LIST.findall(text):
        names += [part.split(" as ")[-1].strip() for part in listed.split(",") if part.strip()]
    return list(dict.fromkeys(names))


def held_said(text: str) -> str:
    """A module, in a line or two: what it exports, the variants it takes."""
    said = []
    names = exported(text)
    if names:
        said.append("exports " + ", ".join(names[:40]))
    for group, values in variants_of(text).items():
        said.append(f"{group}: " + " | ".join(values))
    return " · ".join(said)[:MOST_SAID]


def imported_by(read: Mapping[str, str], tree: Collection[str]) -> list[str]:
    """The repository's modules the files read import, not read themselves,
    the most imported first — MOST_IMPORTED at most."""
    counted: dict[str, int] = {}
    for path, text in read.items():
        if not is_script(path):
            continue
        for _names, spec in imports_of(text):
            target = resolved(spec, path, tree) if is_local(spec) else None
            if target and target not in read:
                counted[target] = counted.get(target, 0) + 1
    return sorted(counted, key=lambda p: (-counted[p], p))[:MOST_IMPORTED]


def unknown_imports(
    after: Mapping[str, str], tree: Collection[str], new: Collection[str] = ()
) -> list[str]:
    """An import of a file of the repository that no file is, nor one this
    change adds: the build fails on it."""
    problems: list[str] = []
    known = set(tree) | set(new)
    for path, text in after.items():
        if not is_script(path) or not text:
            continue
        for _names, spec in imports_of(text):
            if is_local(spec) and resolved(spec, path, known) is None:
                problems.append(
                    f"{path} imports « {spec} », which is no file of the repository: import "
                    "only what exists — a file you were given, one `names_held` lists, or one "
                    "this change adds."
                )
    return list(dict.fromkeys(problems))


def invented_variants(
    after: Mapping[str, str],
    tree: Collection[str],
    variants: Mapping[str, Mapping[str, Sequence[str]]],
) -> list[str]:
    """A component given a variant its module does not declare —
    `<Button variant="primary">` where `variant` is default or outline."""
    problems: list[str] = []
    for path, text in after.items():
        if not path.endswith((".tsx", ".jsx")) or not text:
            continue
        bound: dict[str, str] = {}
        for names, spec in imports_of(text):
            target = resolved(spec, path, tree) if is_local(spec) else None
            if target is not None and target in variants:
                bound.update(dict.fromkeys(names, target))
        for element in _ELEMENT.finditer(text):
            module = bound.get(element.group(1))
            if module is None:
                continue
            for name, value in _ATTRIBUTE.findall(element.group(2)):
                allowed = variants[module].get(name)
                if allowed and value not in allowed:
                    problems.append(
                        f'{path} gives <{element.group(1)} {name}="{value}">: {module} knows '
                        f"{name} {', '.join(allowed)}: use one of those."
                    )
    return list(dict.fromkeys(problems))


def _twice(text: str) -> list[tuple[str, int]]:
    """Each key written twice in one object literal, with the line of the
    second: `{ a: 1, b: 2, a: 3 }`. Strings and comments passed over; a key
    is a name or a quoted string right after « { » or « , » and before « : »,
    in braces — never a function's parameters, in parentheses."""
    found: list[tuple[str, int]] = []
    stack: list[tuple[str, set[str]]] = []
    closes = {")": "(", "]": "[", "}": "{"}
    i, n, line = 0, len(text), 1
    last = ""  # the last significant character before the key being read

    def key(name: str) -> None:
        if stack and stack[-1][0] == "{" and last in "{,":
            if name in stack[-1][1]:
                found.append((name, line))
            stack[-1][1].add(name)

    while i < n:
        char = text[i]
        if char == "\n":
            line += 1
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            line += text.count("\n", i, n if end < 0 else end)
            i = n if end < 0 else end + 2
            continue
        if char in "\"'`":
            end = i + 1
            while end < n and text[end] != char:
                end += 2 if text[end] == "\\" else 1
            literal = text[i + 1 : end]
            line += literal.count("\n")
            if text[end + 1 : end + 40].lstrip(" \t").startswith(":") and "\n" not in literal:
                key(literal)
            i = end + 1
            last = char
            continue
        # An escaped bracket is a regular expression's, never code's.
        escaped = i > 0 and text[i - 1] == "\\"
        if char in "{([" and not escaped:
            stack.append((char, set()))
        elif char in "})]" and not escaped and stack and stack[-1][0] == closes[char]:
            stack.pop()
        match = re.match(r"[A-Za-z_$][\w$]*", text[i:]) if char.isalpha() or char in "_$" else None
        if match:
            name = match.group(0)
            after = text[i + len(name) : i + len(name) + 40].lstrip(" \t")
            if after.startswith(":") and not after.startswith("::"):
                key(name)
            i += len(name)
            last = "a"
            continue
        if not char.isspace():
            last = char
        i += 1
    return found


def written_twice(before: str, after: str, path: str) -> list[str]:
    """A key a change writes a second time into one object — a label added
    that the dictionary already held (2026-10-29, #450: TS1117, the CI red)."""
    if not is_script(path):
        return []
    held = {name for name, _ in _twice(before)}
    return [
        f"{path}: « {name} » is written twice in the same object (line {line}): it is already "
        "there — use the one that exists, never add it again."
        for name, line in _twice(after)
        if name not in held
    ]
