"""A repository's packages, read from its lock file by the server, each
looked up in the public OSV database (2026-10-22: the dependency
analysis).

Every format LEKA reads, from a small real-shaped file; OSV answered by a
MockTransport — the network is never reached, and what is sent to it is
checked: names and versions of public packages, never a private one.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from leka.capabilities import advisories
from leka.capabilities.code_tools import AUDIT_DEPENDENCIES, CODE_NAMES, audited, folders_of
from leka.capabilities.lockfiles import Package, parse
from leka.connectors import CodeRefusedError
from leka.connectors.github import GitHubConfig, GitHubConnector, GitHubCredentials
from leka.connectors.github.code import GitHubCode

OSV = "https://api.osv.example"


def _by_name(path: str, text: str) -> dict[str, Package]:
    parsed = parse(path, text)
    assert parsed is not None
    return {p.name: p for p in parsed.packages}


def test_npm_lock_files_say_what_is_direct_dev_and_private() -> None:
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"express": "^4.18.0"}, "devDependencies": {"jest": "^29"}},
            "node_modules/express": {
                "version": "4.18.2",
                "resolved": "https://registry.npmjs.org/express/-/express-4.18.2.tgz",
            },
            "node_modules/jest": {"version": "29.7.0", "dev": True},
            "node_modules/qs": {"version": "6.11.0"},
            "node_modules/express/node_modules/qs": {"version": "6.5.0"},
            "node_modules/@acme/billing": {
                "version": "1.0.0",
                "resolved": "https://npm.acme.internal/@acme/billing/-/billing-1.0.0.tgz",
            },
            "packages/web": {"version": "0.0.0"},
            "node_modules/web": {"link": True},
        },
    }
    parsed = parse("web/package-lock.json", json.dumps(lock))
    assert parsed is not None and (parsed.ecosystem, parsed.kind) == ("npm", "lock")
    found = {(p.name, p.version): p for p in parsed.packages}
    assert set(found) == {
        ("express", "4.18.2"),
        ("jest", "29.7.0"),
        ("qs", "6.11.0"),
        ("qs", "6.5.0"),
        ("@acme/billing", "1.0.0"),
    }
    assert found[("express", "4.18.2")].direct and not found[("qs", "6.11.0")].direct
    assert found[("jest", "29.7.0")].dev and not found[("express", "4.18.2")].dev
    assert not found[("@acme/billing", "1.0.0")].public


def test_yarn_and_pnpm_lock_files() -> None:
    yarn = (
        "# yarn lockfile v1\n\n"
        '"@babel/code-frame@^7.0.0", "@babel/code-frame@^7.10.4":\n'
        '  version "7.12.13"\n'
        '  resolved "https://registry.yarnpkg.com/@babel/code-frame/-/code-frame-7.12.13.tgz"\n\n'
        "lodash@^4.17.0:\n"
        '  version "4.17.20"\n'
    )
    found = _by_name("yarn.lock", yarn)
    assert (found["@babel/code-frame"].version, found["lodash"].version) == ("7.12.13", "4.17.20")
    berry = (
        '__metadata:\n  version: 6\n\n"left-pad@npm:^1.3.0":\n  version: 1.3.0\n'
        '  resolution: "left-pad@npm:1.3.0"\n\n"web@workspace:.":\n  version: 0.0.0-use.local\n'
        '  resolution: "web@workspace:."\n'
    )
    found = _by_name("yarn.lock", berry)
    assert found["left-pad"].public and not found["web"].public
    pnpm = (
        "lockfileVersion: '9.0'\nimporters:\n  .:\n    dependencies:\n      react:\n"
        "        specifier: ^18.2.0\n        version: 18.2.0\npackages:\n"
        "  react@18.2.0:\n    resolution: {integrity: sha512-x}\n"
        "  '@types/node@20.1.0':\n    resolution: {integrity: sha512-y}\n"
        "  /loose-envify/1.4.0_peer:\n    resolution: {integrity: sha512-z}\n"
    )
    found = _by_name("pnpm-lock.yaml", pnpm)
    assert found["react"].direct and found["react"].version == "18.2.0"
    assert found["@types/node"].version == "20.1.0" and not found["@types/node"].direct
    assert found["loose-envify"].version == "1.4.0"


def test_a_manifest_names_exact_versions_and_lists_ranges_apart() -> None:
    manifest = {
        "dependencies": {"next": "15.0.3", "react": "^18.2.0", "local": "file:../local"},
        "devDependencies": {"vitest": "~1.6.0"},
    }
    parsed = parse("package.json", json.dumps(manifest))
    assert parsed is not None and parsed.kind == "manifest"
    assert [(p.name, p.version, p.direct) for p in parsed.packages] == [("next", "15.0.3", True)]
    assert parsed.ranges == ["react ^18.2.0", "vitest ~1.6.0"]


def test_python_files() -> None:
    requirements = (
        "# pinned\nDjango==4.2.1 \\\n    --hash=sha256:abc\nrequests>=2.31  # any\n"
        "-r base.txt\ngit+https://github.com/acme/tool.git\n"
        "flask[async]==3.0.0 ; python_version>'3'\n"
    )
    parsed = parse("requirements/prod.txt", requirements)
    assert parsed is not None and parsed.kind == "manifest"
    assert {(p.name, p.version) for p in parsed.packages} == {
        ("Django", "4.2.1"),
        ("flask", "3.0.0"),
    }
    assert parsed.ranges == ["requests >=2.31"]
    pinned = parse("requirements.txt", "urllib3==2.0.0\n")
    assert pinned is not None and pinned.kind == "lock"
    uv = (
        'version = 1\n[[package]]\nname = "app"\nversion = "0.1.0"\nsource = { editable = "." }\n'
        'dependencies = [{ name = "fastapi" }]\n\n'
        '[[package]]\nname = "fastapi"\nversion = "0.110.0"\n'
        'source = { registry = "https://pypi.org/simple" }\n\n[[package]]\nname = "starlette"\n'
        'version = "0.36.3"\nsource = { registry = "https://pypi.org/simple" }\n\n'
        '[[package]]\nname = "internal"\nversion = "1.0.0"\n'
        'source = { registry = "https://pypi.acme.internal/simple" }\n'
    )
    found = _by_name("uv.lock", uv)
    assert set(found) == {"fastapi", "starlette", "internal"}
    assert found["fastapi"].direct and found["starlette"].direct is False
    assert not found["internal"].public
    poetry = (
        '[[package]]\nname = "pytest"\nversion = "8.0.0"\ncategory = "dev"\n\n'
        '[[package]]\nname = "tool"\nversion = "1.0"\n[package.source]\ntype = "git"\n'
        'url = "https://github.com/acme/tool"\n'
    )
    found = _by_name("poetry.lock", poetry)
    assert found["pytest"].dev and not found["tool"].public
    pipfile = {
        "default": {"idna": {"version": "==3.4"}},
        "develop": {"black": {"version": "==24.1.0"}},
    }
    found = _by_name("Pipfile.lock", json.dumps(pipfile))
    assert (found["idna"].dev, found["black"].dev) == (False, True)
    pyproject = (
        '[project]\ndependencies = ["httpx==0.27.2", "pydantic>=2"]\n'
        '[tool.poetry.dependencies]\npython = "^3.12"\nrich = "13.7.0"\n'
    )
    parsed = parse("pyproject.toml", pyproject)
    assert parsed is not None
    assert {p.name for p in parsed.packages} == {"httpx", "rich"}
    assert parsed.ranges == ["pydantic >=2"]


def test_go_cargo_ruby_php_maven_and_nuget() -> None:
    go = (
        "module acme.io/api\n\ngo 1.22\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n"
        "\tgolang.org/x/net v0.17.0 // indirect\n)\n\nrequire github.com/google/uuid v1.6.0\n"
    )
    found = _by_name("go.mod", go)
    assert found["github.com/gin-gonic/gin"].version == "1.9.1"
    assert found["github.com/gin-gonic/gin"].direct and found["golang.org/x/net"].direct is False
    assert "github.com/google/uuid" in found
    cargo = (
        '[[package]]\nname = "app"\nversion = "0.1.0"\n\n[[package]]\nname = "serde"\n'
        'version = "1.0.190"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n'
    )
    assert set(_by_name("Cargo.lock", cargo)) == {"serde"}
    gemfile = (
        "GIT\n  remote: https://github.com/acme/gem.git\n  specs:\n    acme (0.1.0)\n\n"
        "GEM\n  remote: https://rubygems.org/\n  specs:\n    nokogiri (1.15.4-x86_64-linux)\n"
        "      racc (~> 1.4)\n    rails (7.1.0)\n\nPLATFORMS\n  ruby\n\n"
        "DEPENDENCIES\n  rails (~> 7.1)\n"
    )
    found = _by_name("Gemfile.lock", gemfile)
    assert found["nokogiri"].version == "1.15.4" and found["rails"].direct
    assert not found["acme"].public and "racc" not in found
    composer = {
        "packages": [
            {
                "name": "symfony/http-kernel",
                "version": "v6.3.0",
                "notification-url": "https://packagist.org/downloads/",
            }
        ],
        "packages-dev": [{"name": "acme/tools", "version": "dev-main"}],
    }
    parsed = parse("composer.lock", json.dumps(composer))
    assert parsed is not None
    assert [(p.name, p.version, p.public) for p in parsed.packages] == [
        ("symfony/http-kernel", "6.3.0", True)
    ]
    assert parsed.ranges == ["acme/tools dev-main"]
    pom = (
        "<project><dependencies><dependency><groupId>org.apache.logging.log4j</groupId>"
        "<artifactId>log4j-core</artifactId><version>2.14.1</version></dependency>"
        "<dependency><groupId>junit</groupId><artifactId>junit</artifactId>"
        "<version>${junit.version}</version><scope>test</scope></dependency>"
        "</dependencies></project>"
    )
    parsed = parse("pom.xml", pom)
    assert parsed is not None
    assert [p.name for p in parsed.packages] == ["org.apache.logging.log4j:log4j-core"]
    assert parsed.ranges == ["junit:junit ${junit.version}"]
    nuget = {
        "dependencies": {
            "net8.0": {
                "Newtonsoft.Json": {"type": "Direct", "resolved": "13.0.1"},
                "System.Text.Json": {"type": "Transitive", "resolved": "8.0.0"},
                "Acme.Core": {"type": "Project"},
            }
        }
    }
    found = _by_name("packages.lock.json", json.dumps(nuget))
    assert set(found) == {"Newtonsoft.Json", "System.Text.Json"}
    assert found["Newtonsoft.Json"].direct and not found["System.Text.Json"].direct


def test_an_unknown_file_is_none_and_a_broken_one_is_said() -> None:
    assert parse("README.md", "# hi") is None


class Osv:
    """OSV's two routes: the batch query, then each advisory."""

    def __init__(self) -> None:
        self.asked: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/querybatch":
            queries = json.loads(request.content)["queries"]
            self.asked += queries
            results = [
                {"vulns": [{"id": "GHSA-qs01"}, {"id": "CVE-2022-24999"}]}
                if q["package"]["name"] == "qs" and q["version"] == "6.5.0"
                else {"vulns": [{"id": "GHSA-ex01"}]}
                if q["package"]["name"] == "express"
                else {}
                for q in queries
            ]
            return httpx.Response(200, json={"results": results})
        advisory = request.url.path.rsplit("/", 1)[-1]
        bodies = {
            "GHSA-qs01": {
                "id": "GHSA-qs01",
                "aliases": ["CVE-2022-24999"],
                "summary": "qs vulnerable to Prototype Pollution",
                "published": "2022-11-26T00:30:50Z",
                "database_specific": {"severity": "HIGH"},
                "affected": [
                    {
                        "package": {"ecosystem": "npm", "name": "qs"},
                        "ranges": [
                            {
                                "type": "SEMVER",
                                "events": [{"introduced": "6.5.0"}, {"fixed": "6.5.3"}],
                            }
                        ],
                    }
                ],
            },
            "GHSA-ex01": {
                "id": "GHSA-ex01",
                "summary": "Open redirect",
                "database_specific": {"severity": "MODERATE"},
            },
        }
        if advisory in bodies:
            return httpx.Response(200, json=bodies[advisory])
        return httpx.Response(404)


LOCK = json.dumps(
    {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"express": "^4.18.0"}},
            "node_modules/express": {"version": "4.18.2"},
            "node_modules/express/node_modules/qs": {"version": "6.5.0"},
            "node_modules/@acme/billing": {
                "version": "1.0.0",
                "resolved": "https://npm.acme.internal/billing-1.0.0.tgz",
            },
        },
    }
)


async def test_each_public_package_is_looked_up_the_worst_first_never_a_private_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    osv = Osv()
    monkeypatch.setattr(advisories, "TRANSPORT", httpx.MockTransport(osv))
    said = await audited(LOCK, "package-lock.json", url=OSV)
    assert {q["package"]["name"] for q in osv.asked} == {"express", "qs"}  # type: ignore[index]
    assert (said["checked"], said["packages"], said["not_public"]) == (True, 3, 1)
    assert said["vulnerable_total"] == 2
    vulnerable = said["vulnerable"]
    assert isinstance(vulnerable, list)
    # The high one first, though transitive; its CVE an alias, not twice.
    assert [v["name"] for v in vulnerable] == ["qs", "express"]
    [qs] = vulnerable[0]["advisories"]
    assert (qs["id"], qs["aliases"], qs["severity"], qs["fixed_in"]) == (
        "GHSA-qs01",
        ["CVE-2022-24999"],
        "high",
        ["6.5.3"],
    )
    assert qs["published"] == "2022-11-26" and qs["url"].endswith("/GHSA-qs01")
    assert vulnerable[1]["advisories"][0]["severity"] == "medium"
    assert vulnerable[1]["direct"] is True


async def test_not_looked_up_unconfigured_or_unreachable_is_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    said = await audited(LOCK, "package-lock.json", url="")
    assert (said["checked"], said["why"], said["packages"]) == (False, "not_configured", 3)

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    monkeypatch.setattr(advisories, "TRANSPORT", httpx.MockTransport(down))
    said = await audited(LOCK, "package-lock.json", url=OSV)
    assert (said["checked"], said["why"]) == (False, "unavailable")
    assert (await audited("{", "package-lock.json", url=""))["error"] == "unreadable"
    assert (await audited("x", "notes.md", url=""))["error"] == "unknown_format"


def test_the_tool_is_a_code_tool_offered_only_to_who_names_it() -> None:
    assert AUDIT_DEPENDENCIES.name in CODE_NAMES
    assert AUDIT_DEPENDENCIES.parameters["required"] == ["repository", "path"]


def _code(handler: object) -> GitHubCode:
    return GitHubCode(
        GitHubConnector(
            GitHubConfig.model_validate({"organization": "acme"}),
            GitHubCredentials(token=SecretStr("github_pat_11ABCDEFG0123456789_testtokenvalue")),
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        )
    )


async def test_a_lock_file_is_read_whole_raw_up_to_a_bound() -> None:
    asked: list[httpx.Request] = []

    def github(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.url.path.endswith("/missing.lock"):
            return httpx.Response(404)
        return httpx.Response(200, content=b"x" * 5_000)

    code = _code(github)
    assert await code.read_whole("acme/api", "yarn.lock", "main") == "x" * 5_000
    assert asked[0].headers["accept"] == "application/vnd.github.raw"
    assert asked[0].url.params["ref"] == "main"
    assert await code.read_whole("acme/api", "missing.lock", "main") is None
    with pytest.raises(CodeRefusedError) as refused:
        await code.read_whole("acme/api", "yarn.lock", "main", most=1_000)
    assert refused.value.code == "too_large"


def test_a_list_cut_says_its_folders() -> None:
    """2026-10-23: a list that stopped before web/ made the designer say the
    repository had no front end; cut, it gives its folders and their files."""
    paths = ["api/app/main.py", "api/alembic/versions/1.py", "web/app/page.tsx", "web/package.json"]
    assert folders_of(paths, "") == {
        "api": 2,
        "api/alembic": 1,
        "api/app": 1,
        "web": 2,
        "web/app": 1,
    }
    assert folders_of(paths, "web") == {"web/app": 1}
