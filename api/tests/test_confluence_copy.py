"""The Confluence copy tool (scripts/confluence_copy): a space's tree, pages
and attachments copied into another Confluence — for a demonstration on a
copy of a customer's documentation, run on the customer's side.

What these protect, on a Confluence faked for the source and for the target:
- `--dry-run` shows the tree — its pages, depth and attachments — and
  writes nothing anywhere; it needs no target.
- A copy keeps the tree: each page under its own parent, parents first; the
  target space made when it is not there; the links to a copied page lead
  to its copy (its space key, and its id in an address); the attachments
  follow their page.
- Run again, it makes no duplicate: what is there unchanged is skipped, a
  page changed since is updated, an attachment there is not sent again.
- Exported to a folder, then imported, it gives the same copy — the side
  that exports never needs the target's credentials.
- A folder of Markdown or HTML files is a tree of pages: a sub-folder is the
  parent of what it holds; a Confluence HTML export keeps a page's content
  only; what Confluence stores is well-formed.
- Confluence Data Center is read with a personal access token.
- A token is never said — not in a message, not in the report.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "confluence_copy", ROOT / "scripts" / "confluence_copy" / "confluence_copy.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["confluence_copy"] = module
    spec.loader.exec_module(module)
    return module


tool = _tool()

SOURCE = "https://client.atlassian.net"
TARGET = "https://leka-demo.atlassian.net"
SOURCE_TOKEN = "src-token-SECRET"
TARGET_TOKEN = "dst-token-SECRET"


class Confluence:
    """One Confluence site's REST API v1, as the tool uses it."""

    def __init__(self, base: str, authorization: str) -> None:
        self.base = base
        self.authorization = authorization
        self.spaces: dict[str, str] = {}
        self.pages: dict[str, dict[str, Any]] = {}
        self.files: dict[str, list[dict[str, Any]]] = {}
        self.next_id = 1000 if "client" in base else 5000
        self.writes: list[tuple[str, str]] = []

    def add(
        self, space: str, title: str, parent: str | None, body: str, *, position: int = 0
    ) -> str:
        self.next_id += 1
        page = str(self.next_id)
        self.pages[page] = {
            "id": page,
            "space": space,
            "title": title,
            "parent": parent,
            "body": body,
            "version": 1,
            "position": position,
        }
        return page

    def _ancestors(self, page: str) -> list[dict[str, str]]:
        chain: list[dict[str, str]] = []
        parent = self.pages[page]["parent"]
        while parent:
            chain.insert(0, {"id": parent})
            parent = self.pages[parent]["parent"]
        return chain

    def _read(self, page: str) -> dict[str, Any]:
        p = self.pages[page]
        return {
            "id": page,
            "type": "page",
            "title": p["title"],
            "ancestors": self._ancestors(page),
            "version": {"number": p["version"]},
            "body": {"storage": {"value": p["body"], "representation": "storage"}},
            "extensions": {"position": p["position"]},
        }

    def _list(self, items: list[dict[str, Any]], query: Mapping[str, str]) -> dict[str, Any]:
        start, limit = int(query.get("start", 0)), int(query.get("limit", 25))
        return {"results": items[start : start + limit], "size": len(items[start : start + limit])}

    def __call__(
        self, method: str, path: str, query: Mapping[str, str], request: urllib.request.Request
    ) -> tuple[int, dict[str, str], bytes]:
        if request.get_header("Authorization") != self.authorization:
            return 401, {}, b'{"message": "Unauthorized"}'
        if method != "GET":
            self.writes.append((method, path))

        def ok(found: object) -> tuple[int, dict[str, str], bytes]:
            return 200, {}, json.dumps(found).encode()

        if method == "GET" and (m := re.fullmatch(r"/rest/api/space/(\w+)", path)):
            key = m.group(1)
            return (
                ok({"key": key, "name": self.spaces[key]}) if key in self.spaces else (404, {}, b"")
            )
        if method == "POST" and path == "/rest/api/space":
            body = json.loads(_sent(request) or b"{}")
            self.spaces[body["key"]] = body["name"]
            return ok(body)
        if method == "GET" and path == "/rest/api/content":
            found = [
                self._read(p)
                for p, page in self.pages.items()
                if page["space"] == query.get("spaceKey")
                and ("title" not in query or page["title"] == query["title"])
            ]
            return ok(self._list(found, query))
        if method == "POST" and path == "/rest/api/content":
            body = json.loads(_sent(request) or b"{}")
            ancestors = body.get("ancestors") or []
            page = self.add(
                body["space"]["key"],
                body["title"],
                str(ancestors[-1]["id"]) if ancestors else None,
                body["body"]["storage"]["value"],
            )
            return ok({"id": page})
        if m := re.fullmatch(r"/rest/api/content/(\d+)", path):
            page = m.group(1)
            if page not in self.pages:
                return 404, {}, b""
            if method == "PUT":
                body = json.loads(_sent(request) or b"{}")
                ancestors = body.get("ancestors") or []
                self.pages[page].update(
                    title=body["title"],
                    body=body["body"]["storage"]["value"],
                    parent=str(ancestors[-1]["id"]) if ancestors else None,
                    version=body["version"]["number"],
                )
            return ok(self._read(page))
        if m := re.fullmatch(r"/rest/api/content/(\d+)/descendant/page", path):
            root = m.group(1)
            found = [self._read(p) for p in self.pages if {"id": root} in self._ancestors(p)]
            return ok(self._list(found, query))
        if m := re.fullmatch(r"/rest/api/content/(\d+)/child/attachment", path):
            page = m.group(1)
            had = self.files.setdefault(page, [])
            if method == "POST":
                assert request.get_header("X-atlassian-token") == "no-check"
                raw = _sent(request)
                named = re.search(rb'filename="([^"]+)"', raw)
                assert named is not None
                content = raw.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
                had.append({"title": named.group(1).decode(), "data": content})
                return ok({"results": []})
            found = [
                {
                    "title": f["title"],
                    "metadata": {"mediaType": "image/png"},
                    "extensions": {"fileSize": len(f["data"])},
                    "_links": {"download": f"/download/attachments/{page}/{f['title']}"},
                }
                for f in had
                if "filename" not in query or f["title"] == query["filename"]
            ]
            return ok(self._list(found, query))
        if m := re.fullmatch(r"/download/attachments/(\d+)/(.+)", path):
            title = urllib.parse.unquote(m.group(2))
            [file] = [f for f in self.files[m.group(1)] if f["title"] == title]
            return 200, {}, bytes(file["data"])
        return 500, {}, f"unexpected {method} {path}".encode()


def _sent(request: urllib.request.Request) -> bytes:
    """What a request carried."""
    data = request.data
    assert data is None or isinstance(data, bytes)
    return data or b""


def _basic(email: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


class Sites:
    """Both sites, the opener the tool is given."""

    def __init__(self, source: Confluence, target: Confluence) -> None:
        self.sites = {source.base: source, target.base: target}

    def __call__(self, request: urllib.request.Request) -> tuple[int, dict[str, str], bytes]:
        url = urllib.parse.urlsplit(request.full_url)
        for base, site in self.sites.items():
            prefix = urllib.parse.urlsplit(base)
            if url.netloc == prefix.netloc and url.path.startswith(prefix.path):
                query = dict(urllib.parse.parse_qsl(url.query))
                return site(request.get_method(), url.path[len(prefix.path) :], query, request)
        raise AssertionError(f"reached {request.full_url}")


def _source() -> tuple[Confluence, dict[str, str]]:
    source = Confluence(f"{SOURCE}/wiki", _basic("rachid@client.example", SOURCE_TOKEN))
    source.spaces["ARCHI"] = "Architecture applicative"
    home = source.add("ARCHI", "Accueil", None, "<p>Le SI.</p>")
    journey = source.add(
        "ARCHI", "Parcours Paiement", home, "<p>Voir la couche métier.</p>", position=1
    )
    business = source.add(
        "ARCHI",
        "Couche métier",
        journey,
        '<p>Lié à <ac:link><ri:page ri:space-key="ARCHI" ri:content-title="Couche applicative" />'
        "</ac:link></p>",
        position=0,
    )
    application = source.add("ARCHI", "Couche applicative", journey, "<p>x</p>", position=1)
    source.pages[journey]["body"] = (
        f'<p><a href="{SOURCE}/wiki/pages/viewpage.action?pageId={business}">métier</a> et '
        f'<a href="{SOURCE}/wiki/spaces/ARCHI/pages/{application}/Couche">appli</a></p>'
    )
    source.files[business] = [{"title": "schema.png", "data": b"\x89PNG-bytes"}]
    return source, {
        "home": home,
        "journey": journey,
        "business": business,
        "application": application,
    }


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tool, "HERE", tmp_path)
    for key, value in {
        "SOURCE_URL": SOURCE,
        "SOURCE_EMAIL": "rachid@client.example",
        "SOURCE_TOKEN": SOURCE_TOKEN,
        "TARGET_URL": TARGET,
        "TARGET_EMAIL": "demo@leka.example",
        "TARGET_TOKEN": TARGET_TOKEN,
    }.items():
        monkeypatch.setenv(key, value)
    return tmp_path


def _target() -> Confluence:
    return Confluence(f"{TARGET}/wiki", _basic("demo@leka.example", TARGET_TOKEN))


def _by_title(site: Confluence, space: str) -> dict[str, dict[str, Any]]:
    return {p["title"]: p for p in site.pages.values() if p["space"] == space}


def test_a_dry_run_shows_the_tree_and_writes_nothing(env: Path) -> None:
    source, _ = _source()
    target = _target()
    said: list[str] = []
    code = tool.main(
        ["copy", "--space", "ARCHI", "--dry-run"], opener=Sites(source, target), say=said.append
    )
    assert code == 0
    tree = [line for line in said if "•" in line]
    assert tree == [
        "• Accueil",
        "  • Parcours Paiement",
        "    • Couche métier  (1 pièce(s) jointe(s))",
        "    • Couche applicative",
    ]
    assert "4 pages, 3 niveau(x), 1 pièce(s) jointe(s)." in said[-1]
    assert source.writes == [] and target.writes == []
    assert not (env / tool.REPORT).exists()


def test_a_copy_keeps_the_tree_its_links_and_files_and_runs_again_without_duplicates(
    env: Path,
) -> None:
    source, ids = _source()
    target = _target()
    sites = Sites(source, target)
    said: list[str] = []
    assert (
        tool.main(
            ["copy", "--space", "ARCHI", "--target-space", "DEMO"], opener=sites, say=said.append
        )
        == 0
    )

    # The space made, each page under its own parent.
    assert target.spaces == {"DEMO": "Architecture applicative"}
    copied = _by_title(target, "DEMO")
    assert set(copied) == {"Accueil", "Parcours Paiement", "Couche métier", "Couche applicative"}
    parent = {
        t: (target.pages[p["parent"]]["title"] if p["parent"] else None) for t, p in copied.items()
    }
    assert parent == {
        "Accueil": None,
        "Parcours Paiement": "Accueil",
        "Couche métier": "Parcours Paiement",
        "Couche applicative": "Parcours Paiement",
    }
    # Its links lead to the copies: the space key, and the ids in addresses.
    assert 'ri:space-key="DEMO"' in copied["Couche métier"]["body"]
    journey = copied["Parcours Paiement"]["body"]
    assert f'"{TARGET}/wiki/spaces/DEMO/pages/{copied["Couche métier"]["id"]}"' in journey
    assert f"{TARGET}/wiki/spaces/DEMO/pages/{copied['Couche applicative']['id']}/Couche" in journey
    assert SOURCE not in journey and ids["business"] not in journey
    # The attachment, its bytes, on its page.
    assert target.files[copied["Couche métier"]["id"]] == [
        {"title": "schema.png", "data": b"\x89PNG-bytes"}
    ]
    report = json.loads((env / tool.REPORT).read_text(encoding="utf-8"))
    assert len(report["créées"]) == 4 and report["en_erreur"] == []
    assert report["pièces_jointes"] == 1

    # Again: nothing made twice, nothing sent again.
    pages, files = len(target.pages), sum(len(f) for f in target.files.values())
    said.clear()
    assert (
        tool.main(
            ["copy", "--space", "ARCHI", "--target-space", "DEMO"], opener=sites, say=said.append
        )
        == 0
    )
    assert (len(target.pages), sum(len(f) for f in target.files.values())) == (pages, files)
    again = json.loads((env / tool.REPORT).read_text(encoding="utf-8"))
    assert (len(again["créées"]), len(again["ignorées"])) == (0, 4)

    # A page changed at the source since: updated, the others skipped.
    source.pages[ids["application"]]["body"] = "<p>Nouvelle version.</p>"
    assert (
        tool.main(
            ["copy", "--space", "ARCHI", "--target-space", "DEMO"], opener=sites, say=said.append
        )
        == 0
    )
    changed = json.loads((env / tool.REPORT).read_text(encoding="utf-8"))
    assert changed["mises_à_jour"] == ["Couche applicative"]
    assert _by_title(target, "DEMO")["Couche applicative"]["body"] == "<p>Nouvelle version.</p>"


def test_a_page_and_its_children_only(env: Path) -> None:
    source, ids = _source()
    target = _target()
    code = tool.main(
        ["copy", "--space", "ARCHI", "--root-page", ids["journey"]],
        opener=Sites(source, target),
        say=lambda _: None,
    )
    assert code == 0
    copied = _by_title(target, "ARCHI")
    assert set(copied) == {"Parcours Paiement", "Couche métier", "Couche applicative"}
    assert copied["Parcours Paiement"]["parent"] is None


def test_exported_then_imported_it_is_the_same_copy(env: Path) -> None:
    source, _ = _source()
    out = env / "export"
    assert (
        tool.main(
            ["export", "--space", "ARCHI", "--out", str(out)],
            opener=Sites(source, _target()),
            say=lambda _: None,
        )
        == 0
    )
    assert (out / "arborescence.txt").read_text(encoding="utf-8").splitlines() == [
        "Accueil",
        "  Parcours Paiement",
        "    Couche métier",
        "    Couche applicative",
    ]
    # The side that imports has no source at all.
    target = _target()
    alone = Sites(Confluence("https://nowhere.example", "none"), target)
    assert (
        tool.main(
            ["import", "--from", str(out), "--target-space", "DEMO"],
            opener=alone,
            say=lambda _: None,
        )
        == 0
    )
    copied = _by_title(target, "DEMO")
    assert target.pages[copied["Couche métier"]["parent"]]["title"] == "Parcours Paiement"
    assert target.files[copied["Couche métier"]["id"]][0]["data"] == b"\x89PNG-bytes"


def _well_formed(body: str) -> None:
    namespaces = 'xmlns:ac="urn:ac" xmlns:ri="urn:ri"'
    # What the tool wrote, parsed to prove it well-formed — nothing untrusted.
    ElementTree.fromstring(f"<root {namespaces}>{body}</root>")  # noqa: S314


def test_a_folder_of_markdown_and_html_is_a_tree_of_pages(env: Path) -> None:
    folder = env / "pages"
    (folder / "Architecture").mkdir(parents=True)
    (folder / "Architecture.md").write_text(
        "# Architecture applicative\n\nLe **SI** de `paiement`.\n\n"
        "## Couches\n\n- métier\n- applicative\n\n"
        "| Brique | Rôle |\n|---|---|\n| API | Payer |\n\n```sql\nselect 1;\n```\n",
        encoding="utf-8",
    )
    (folder / "Architecture" / "01 Couche métier.md").write_text("Les acteurs.\n", encoding="utf-8")
    (folder / "Architecture" / "Flux.html").write_text(
        "<html><head><title>ARCHI : Flux</title><script>x()</script></head><body>"
        '<div id="breadcrumbs">Accueil &gt; Flux</div>'
        '<div id="main-content"><p>Un flux<br>vers <b>Payer</b></p><img src="a.png"></div>'
        '<div id="footer">Généré par Confluence</div></body></html>',
        encoding="utf-8",
    )
    target = _target()
    sites = Sites(Confluence("https://nowhere.example", "none"), target)
    said: list[str] = []
    assert (
        tool.main(
            ["import", "--from", str(folder), "--dry-run", "--target-space", "DEMO"],
            opener=sites,
            say=said.append,
        )
        == 0
    )
    assert target.writes == []
    code = tool.main(
        ["import", "--from", str(folder), "--target-space", "DEMO", "--space-name", "Démo"],
        opener=sites,
        say=lambda _: None,
    )
    assert code == 0
    copied = _by_title(target, "DEMO")
    assert set(copied) == {"Architecture applicative", "Couche métier", "Flux"}
    top = copied["Architecture applicative"]
    assert top["parent"] is None
    assert target.pages[copied["Couche métier"]["parent"]]["title"] == "Architecture applicative"
    for page in copied.values():
        _well_formed(page["body"])
    assert "<strong>SI</strong>" in top["body"] and "<code>paiement</code>" in top["body"]
    assert "<ul><li>métier</li><li>applicative</li></ul>" in top["body"]
    assert "<th>Brique</th>" in top["body"] and 'ac:name="code"' in top["body"]
    flux = copied["Flux"]["body"]
    assert "Un flux<br />vers <b>Payer</b>" in flux
    assert "x()" not in flux and "Accueil &gt; Flux" not in flux and "Généré" not in flux


def test_data_center_is_read_with_a_personal_access_token(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_URL", "https://confluence.client.example")
    monkeypatch.setenv("SOURCE_EMAIL", "")
    source = Confluence("https://confluence.client.example", f"Bearer {SOURCE_TOKEN}")
    source.spaces["ARCHI"] = "Architecture"
    source.add("ARCHI", "Accueil", None, "<p>x</p>")
    target = _target()
    assert (
        tool.main(["copy", "--space", "ARCHI"], opener=Sites(source, target), say=lambda _: None)
        == 0
    )
    assert set(_by_title(target, "ARCHI")) == {"Accueil"}


def test_a_token_is_never_said(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, _ = _source()
    monkeypatch.setenv("SOURCE_TOKEN", "wrong-SECRET")
    said: list[str] = []
    code = tool.main(["copy", "--space", "ARCHI"], opener=Sites(source, _target()), say=said.append)
    assert code == 2
    assert "Accès refusé" in said[-1]
    assert all("SECRET" not in line for line in said)
    # A missing configuration is said, with where to fix it.
    monkeypatch.delenv("SOURCE_TOKEN")
    said.clear()
    assert (
        tool.main(["copy", "--space", "ARCHI"], opener=Sites(source, _target()), say=said.append)
        == 2
    )
    assert "SOURCE_TOKEN" in said[-1] and ".env" in said[-1]
