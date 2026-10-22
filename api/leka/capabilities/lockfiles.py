"""A repository's third-party packages, read from its lock file or its
manifest by the server itself (2026-10-22: the dependency analysis).

A lock file runs to thousands of lines: given to a model as it is, it is
cut, or copied wrong. Parsed here, every package comes out exact — its
name, the version installed, whether the project asks for it itself
(direct) or gets it through another (transitive), whether it serves only
development — and the model is given the list, never the file.

Read as data, never run: no package manager, no install, no script. What
a file does not say stays unsaid (`direct=None`). A package from a private
registry, a path or a git repository is marked `public=False`: its name is
never sent anywhere (advisories.py).

The formats, by file name:

    npm        package-lock.json, npm-shrinkwrap.json, yarn.lock,
               pnpm-lock.yaml — package.json, the manifest
    PyPI       poetry.lock, uv.lock, pdm.lock, Pipfile.lock,
               requirements*.txt — pyproject.toml, the manifest
    Go         go.mod
    crates.io  Cargo.lock
    RubyGems   Gemfile.lock
    Packagist  composer.lock
    Maven      pom.xml, the manifest
    NuGet      packages.lock.json

A manifest names what the project asks for, often as a range (^1.2):
an exact version is a package, a range is listed apart — what it installs
is decided at install time, by a lock file when there is one.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import yaml

# What one file gives, at most.
MOST_PACKAGES = 10_000

PUBLIC_NPM = frozenset({"registry.npmjs.org", "registry.yarnpkg.com", "registry.npmmirror.com"})
EXACT = re.compile(r"v?\d+(?:\.\d+){0,3}(?:[-+][0-9A-Za-z.\-+]+)?")


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    # None: the file does not say.
    direct: bool | None = None
    dev: bool | None = None
    # From the public registry, as far as the file says.
    public: bool = True


@dataclass
class Parsed:
    """One file's packages, in OSV's names for ecosystems."""

    ecosystem: str
    # "lock": every package installed; "manifest": what the project asks for.
    kind: str
    packages: list[Package] = field(default_factory=list)
    # Asked without an exact version: "name range".
    ranges: list[str] = field(default_factory=list)

    def add(self, package: Package) -> None:
        if package.name and package.version and len(self.packages) < MOST_PACKAGES:
            self.packages.append(package)

    def unique(self) -> Parsed:
        """Each name and version once, the most that is known of it kept."""
        seen: dict[tuple[str, str], Package] = {}
        for p in self.packages:
            known = seen.get((p.name, p.version))
            if known is None:
                seen[(p.name, p.version)] = p
            else:
                seen[(p.name, p.version)] = Package(
                    p.name,
                    p.version,
                    direct=_either(known.direct, p.direct),
                    # Development only when every copy is.
                    dev=_both(known.dev, p.dev),
                    public=known.public and p.public,
                )
        self.packages = list(seen.values())
        self.ranges = sorted(set(self.ranges))
        return self


def _either(a: bool | None, b: bool | None) -> bool | None:
    if a or b:
        return True
    return None if a is None and b is None else False


def _both(a: bool | None, b: bool | None) -> bool | None:
    if a is False or b is False:
        return False
    return True if a and b else None


class UnreadableError(ValueError):
    """A file of a known format that does not read as one."""


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as error:
        raise UnreadableError(str(error)) from error


def _toml(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise UnreadableError(str(error)) from error


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


# ── npm ──────────────────────────────────────────────────────────────────


def _npm_lock(text: str) -> Parsed:
    data = _dict(_json(text))
    found = Parsed("npm", "lock")
    packages = _dict(data.get("packages"))
    if packages:
        root = _dict(packages.get(""))
        asked = {
            name
            for part in ("dependencies", "devDependencies", "optionalDependencies")
            for name in _dict(root.get(part))
        }
        for path, raw in packages.items():
            entry = _dict(raw)
            if not path or entry.get("link") or "node_modules/" not in path:
                continue
            name = str(entry.get("name") or path.rsplit("node_modules/", 1)[-1])
            resolved = str(entry.get("resolved") or "")
            found.add(
                Package(
                    name,
                    str(entry.get("version") or ""),
                    direct=path == f"node_modules/{name}" and name in asked,
                    dev=bool(entry.get("dev") or entry.get("devOptional")),
                    public=not resolved or _host(resolved) in PUBLIC_NPM,
                )
            )
        return found.unique()

    # Version 1: nested, the project's own list not kept.
    def walk(dependencies: Mapping[str, Any]) -> None:
        for name, raw in dependencies.items():
            entry = _dict(raw)
            resolved = str(entry.get("resolved") or "")
            version = str(entry.get("version") or "")
            local = version.startswith(("file:", "git+", "git:", "http://", "https://", "link:"))
            found.add(
                Package(
                    name,
                    version,
                    dev=bool(entry.get("dev")),
                    public=not local and (not resolved or _host(resolved) in PUBLIC_NPM),
                )
            )
            walk(_dict(entry.get("dependencies")))

    walk(_dict(data.get("dependencies")))
    return found.unique()


_YARN_HEAD = re.compile(r'^"?((?:@[^@/"\s]+/)?[^@"\s]+)@')


def _yarn_lock(text: str) -> Parsed:
    found = Parsed("npm", "lock")
    name: str | None = None
    version = resolved = ""

    def close() -> None:
        if name is None or not version:
            return
        local = any(f"@{k}:" in resolved for k in ("workspace", "patch", "link", "portal", "file"))
        public = not local and (
            "@npm:" in resolved or not resolved or _host(resolved) in PUBLIC_NPM
        )
        found.add(Package(name, version, public=public))

    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith(" "):
            close()
            head = _YARN_HEAD.match(line.strip())
            name = head.group(1) if head and not line.startswith("__metadata") else None
            version = resolved = ""
            continue
        said = line.strip()
        for keyword in ("version", "resolved", "resolution"):
            if said.startswith(keyword + " ") or said.startswith(keyword + ":"):
                value = said[len(keyword) :].lstrip(": ").strip().strip('"')
                if keyword == "version":
                    version = value
                else:
                    resolved = value
    close()
    return found.unique()


def _pnpm_key(key: str) -> tuple[str, str] | None:
    """/name/1.2.3_peer (v5), /name@1.2.3(peer) (v6), name@1.2.3 (v9)."""
    key = key.lstrip("/").split("(", 1)[0]
    at = key.rfind("@")
    if at > 0:
        return key[:at], key[at + 1 :]
    parts = key.split("/")
    if len(parts) < 2:
        return None
    return "/".join(parts[:-1]), parts[-1].split("_", 1)[0]


def _pnpm_lock(text: str) -> Parsed:
    try:
        data = _dict(yaml.safe_load(text))
    except yaml.YAMLError as error:
        raise UnreadableError(str(error)) from error
    found = Parsed("npm", "lock")
    importer = _dict(_dict(data.get("importers")).get(".")) or data
    asked = {
        name
        for part in ("dependencies", "devDependencies", "optionalDependencies")
        for name in _dict(importer.get(part))
    }
    for key, raw in _dict(data.get("packages")).items():
        named = _pnpm_key(str(key))
        if named is None:
            continue
        entry = _dict(raw)
        tarball = str(_dict(entry.get("resolution")).get("tarball") or "")
        local = named[1].startswith(("link:", "file:")) or (
            bool(tarball) and _host(tarball) not in PUBLIC_NPM
        )
        found.add(
            Package(
                named[0],
                named[1],
                direct=named[0] in asked,
                dev=bool(entry["dev"]) if "dev" in entry else None,
                public=not local,
            )
        )
    return found.unique()


def _package_json(text: str) -> Parsed:
    data = _dict(_json(text))
    found = Parsed("npm", "manifest")
    for part in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, spec in _dict(data.get(part)).items():
            said = str(spec).strip()
            if said.startswith(
                (
                    "file:",
                    "link:",
                    "workspace:",
                    "git+",
                    "git:",
                    "http://",
                    "https://",
                    "github:",
                    ".",
                )
            ):
                continue
            if said.startswith("npm:"):
                continue
            if EXACT.fullmatch(said):
                found.add(
                    Package(name, said.lstrip("v"), direct=True, dev=part == "devDependencies")
                )
            else:
                found.ranges.append(f"{name} {said}")
    return found.unique()


# ── PyPI ─────────────────────────────────────────────────────────────────

_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def _pep508(line: str) -> tuple[str, str] | None:
    """A requirement's name and what it asks: "==1.2.3", ">=2", ""."""
    said = line.split(";", 1)[0].strip()
    if (
        not said
        or said.startswith(("-", "git+", "http://", "https://", ".", "/", "file:"))
        or " @ " in said
    ):
        return None
    match = _REQUIREMENT.match(said)
    if match is None:
        return None
    return match.group(1), match.group(3).replace(" ", "")


def _python_asked(found: Parsed, asked: Iterable[str], *, dev: bool | None = None) -> None:
    for line in asked:
        named = _pep508(str(line))
        if named is None:
            continue
        name, spec = named
        if spec.startswith("==") and "*" not in spec and "," not in spec:
            found.add(Package(name, spec[2:], direct=True, dev=dev))
        else:
            found.ranges.append(f"{name} {spec or '(any)'}")


def _requirements(text: str) -> Parsed:
    found = Parsed("PyPI", "manifest")
    lines: list[str] = []
    for raw in text.replace("\\\n", " ").splitlines():
        said = raw.split(" #", 1)[0].strip()
        if said and not said.startswith("#"):
            lines.append(said.split(" --hash", 1)[0])
    _python_asked(found, lines)
    # Every requirement pinned is what a lock says: what is installed.
    if found.packages and not found.ranges:
        found.kind = "lock"
    return found.unique()


def _local(source: object) -> bool:
    """A package of the project's own, by path (uv's sources)."""
    return isinstance(source, dict) and any(
        k in source for k in ("editable", "virtual", "directory", "path")
    )


def _python_lock(text: str) -> Parsed:
    """poetry.lock, uv.lock, pdm.lock: [[package]] tables."""
    data = _toml(text)
    found = Parsed("PyPI", "lock")
    # The project itself (uv): what it asks for is direct.
    direct = {
        str(_dict(d).get("name") or "").lower()
        for raw in _list(data.get("package"))
        if _local(_dict(raw).get("source"))
        for d in _list(_dict(raw).get("dependencies"))
    }
    for raw in _list(data.get("package")):
        entry = _dict(raw)
        source = entry.get("source")
        public = True
        if _local(source):
            continue
        if isinstance(source, dict):
            if "git" in source or "url" in source:
                public = False
            registry = str(source.get("registry") or "")
            if registry and _host(registry) not in ("pypi.org", "files.pythonhosted.org"):
                public = False
            kind = str(source.get("type") or "")
            if kind in ("git", "directory", "file", "url"):
                public = False
            if kind == "legacy" and _host(str(source.get("url") or "")) != "pypi.org":
                public = False
        name = str(entry.get("name") or "")
        category = entry.get("category")
        found.add(
            Package(
                name,
                str(entry.get("version") or ""),
                direct=name.lower() in direct if direct else None,
                dev=category == "dev" if category else None,
                public=public,
            )
        )
    return found.unique()


def _pipfile_lock(text: str) -> Parsed:
    data = _dict(_json(text))
    found = Parsed("PyPI", "lock")
    for part, dev in (("default", False), ("develop", True)):
        for name, raw in _dict(data.get(part)).items():
            entry = _dict(raw)
            version = str(entry.get("version") or "")
            if not version.startswith("=="):
                continue
            local = any(k in entry for k in ("git", "path", "file", "editable"))
            found.add(Package(name, version[2:], dev=dev, public=not local))
    return found.unique()


def _pyproject(text: str) -> Parsed:
    data = _toml(text)
    found = Parsed("PyPI", "manifest")
    project = _dict(data.get("project"))
    _python_asked(found, _list(project.get("dependencies")), dev=False)
    for asked in _dict(project.get("optional-dependencies")).values():
        _python_asked(found, _list(asked))
    for asked in _dict(data.get("dependency-groups")).values():
        _python_asked(found, [a for a in _list(asked) if isinstance(a, str)], dev=True)
    poetry = _dict(_dict(data.get("tool")).get("poetry"))
    groups = [(_dict(poetry.get("dependencies")), False)] + [
        (_dict(_dict(g).get("dependencies")), True) for g in _dict(poetry.get("group")).values()
    ]
    for asked, dev in groups:
        for name, spec in asked.items():
            if name.lower() == "python":
                continue
            said = spec if isinstance(spec, str) else str(_dict(spec).get("version") or "")
            if isinstance(spec, dict) and any(k in spec for k in ("git", "path", "url")):
                continue
            if EXACT.fullmatch(said):
                found.add(Package(name, said, direct=True, dev=dev))
            else:
                found.ranges.append(f"{name} {said or '(any)'}")
    return found.unique()


# ── the others ───────────────────────────────────────────────────────────

_GO_REQUIRE = re.compile(r"^(\S+)\s+(v\S+)(\s*//\s*indirect)?")


def _go_mod(text: str) -> Parsed:
    found = Parsed("Go", "lock")
    block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("require ("):
            block = True
            continue
        if block and line == ")":
            block = False
            continue
        said = line[len("require ") :].strip() if line.startswith("require ") else line
        if not (block or line.startswith("require ")):
            continue
        match = _GO_REQUIRE.match(said)
        if match:
            found.add(
                Package(
                    match.group(1),
                    match.group(2).removeprefix("v"),
                    direct=match.group(3) is None,
                )
            )
    return found.unique()


def _cargo_lock(text: str) -> Parsed:
    data = _toml(text)
    found = Parsed("crates.io", "lock")
    for raw in _list(data.get("package")):
        entry = _dict(raw)
        source = str(entry.get("source") or "")
        if not source:
            # The workspace's own crates.
            continue
        public = source.startswith(
            (
                "registry+https://github.com/rust-lang/crates.io-index",
                "sparse+https://index.crates.io",
            )
        )
        found.add(
            Package(str(entry.get("name") or ""), str(entry.get("version") or ""), public=public)
        )
    return found.unique()


_GEM = re.compile(r"^    ([^\s(]+) \(([^)]+)\)$")


def _gemfile_lock(text: str) -> Parsed:
    found = Parsed("RubyGems", "lock")
    section = remote = ""
    asked: set[str] = set()
    gems: list[tuple[str, str, bool]] = []
    for line in text.splitlines():
        if line and not line.startswith(" "):
            section = line.strip()
            remote = ""
            continue
        said = line.strip()
        if said.startswith("remote:"):
            remote = said[len("remote:") :].strip()
        if section == "DEPENDENCIES" and line.startswith("  ") and not line.startswith("   "):
            asked.add(said.split(" ", 1)[0].rstrip("!"))
        match = _GEM.match(line)
        if match and section in ("GEM", "GIT", "PATH"):
            public = section == "GEM" and _host(remote) in ("rubygems.org", "")
            gems.append((match.group(1), match.group(2).split("-", 1)[0], public))
    for name, version, public in gems:
        found.add(Package(name, version, direct=name in asked if asked else None, public=public))
    return found.unique()


def _composer_lock(text: str) -> Parsed:
    data = _dict(_json(text))
    found = Parsed("Packagist", "lock")
    for part, dev in (("packages", False), ("packages-dev", True)):
        for raw in _list(data.get(part)):
            entry = _dict(raw)
            version = str(entry.get("version") or "")
            if version.startswith("dev-"):
                found.ranges.append(f"{entry.get('name')} {version}")
                continue
            public = _host(str(entry.get("notification-url") or "")) == "packagist.org"
            found.add(
                Package(
                    str(entry.get("name") or ""), version.removeprefix("v"), dev=dev, public=public
                )
            )
    return found.unique()


_POM_DEPENDENCY = re.compile(r"<dependency>(.*?)</dependency>", re.S)


def _pom_tag(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*([^<]*?)\s*</{tag}>", block)
    return match.group(1) if match else ""


def _pom_xml(text: str) -> Parsed:
    """Read with patterns, never an XML parser: no entity is ever expanded."""
    found = Parsed("Maven", "manifest")
    for block in _POM_DEPENDENCY.findall(text):
        group, artifact = _pom_tag(block, "groupId"), _pom_tag(block, "artifactId")
        version = _pom_tag(block, "version")
        if not group or not artifact:
            continue
        name = f"{group}:{artifact}"
        if not version or "${" in version or version.startswith(("[", "(")):
            found.ranges.append(f"{name} {version or '(managed)'}")
            continue
        found.add(Package(name, version, direct=True, dev=_pom_tag(block, "scope") == "test"))
    return found.unique()


def _nuget_lock(text: str) -> Parsed:
    data = _dict(_json(text))
    found = Parsed("NuGet", "lock")
    for target in _dict(data.get("dependencies")).values():
        for name, raw in _dict(target).items():
            entry = _dict(raw)
            kind = str(entry.get("type") or "")
            if kind == "Project":
                continue
            found.add(Package(name, str(entry.get("resolved") or ""), direct=kind == "Direct"))
    return found.unique()


PARSERS: dict[str, Callable[[str], Parsed]] = {
    "package-lock.json": _npm_lock,
    "npm-shrinkwrap.json": _npm_lock,
    "yarn.lock": _yarn_lock,
    "pnpm-lock.yaml": _pnpm_lock,
    "package.json": _package_json,
    "poetry.lock": _python_lock,
    "uv.lock": _python_lock,
    "pdm.lock": _python_lock,
    "Pipfile.lock": _pipfile_lock,
    "pyproject.toml": _pyproject,
    "go.mod": _go_mod,
    "Cargo.lock": _cargo_lock,
    "Gemfile.lock": _gemfile_lock,
    "composer.lock": _composer_lock,
    "pom.xml": _pom_xml,
    "packages.lock.json": _nuget_lock,
}
KNOWN = (*PARSERS, "requirements*.txt")


def parser_for(path: str) -> Callable[[str], Parsed] | None:
    name = path.rsplit("/", 1)[-1]
    if name in PARSERS:
        return PARSERS[name]
    if name.endswith(".txt") and ("requirements" in name or "/requirements/" in f"/{path}"):
        return _requirements
    return None


def parse(path: str, text: str) -> Parsed | None:
    """The packages one file names — None for a file of no known format;
    UnreadableError for one that does not read as its format."""
    found = parser_for(path)
    return found(text) if found else None


__all__ = ["KNOWN", "Package", "Parsed", "UnreadableError", "parse", "parser_for"]
