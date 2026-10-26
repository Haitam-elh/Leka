"""Confluence, read — never written: by its REST API (Cloud or Data Center),
or from a folder on disk (an export of the copy tool, or Markdown and HTML
files whose folders are the parent pages).

    Site            a Confluence and how to present oneself: its address, the
                    account's email and API token (Cloud), or a personal
                    access token alone (Data Center)
    read_space()    a space — or a page and every page under it — as Pages
    read_folder()   the same, from a folder
    text_of()       a page's storage format, as text a model reads

The token never appears in a message: an address said is said without it.
Only the standard library: it runs on any Python from 3.9.
"""

from __future__ import annotations

import base64
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .pages import Page

TIMEOUT = 60
RETRIES = 4
PAGE_SIZE = 50
EXPAND = "ancestors,version,body.storage"


class ConfluenceError(Exception):
    """What Confluence refused, said so a person can act on it."""


@dataclass(frozen=True)
class Site:
    url: str
    email: str = ""
    token: str = field(default="", repr=False)

    @property
    def cloud(self) -> bool:
        return ".atlassian.net" in urllib.parse.urlsplit(self.url).netloc

    @property
    def base(self) -> str:
        """Where its API starts: /wiki on Cloud, the address given otherwise."""
        url = self.url.rstrip("/")
        if self.cloud and not url.endswith("/wiki"):
            url += "/wiki"
        return url

    @property
    def authorization(self) -> str:
        if self.email:
            pair = f"{self.email}:{self.token}".encode()
            return "Basic " + base64.b64encode(pair).decode()
        return f"Bearer {self.token}"

    def page_url(self, page_id: str) -> str:
        return f"{self.base}/pages/viewpage.action?pageId={urllib.parse.quote(page_id)}"


def checked(site: Site) -> Site:
    """A site that may be called: https, with a token."""
    if not site.url.startswith("https://") and not site.url.startswith("http://localhost"):
        raise ConfluenceError("L'adresse de Confluence doit commencer par https://.")
    if not site.token:
        raise ConfluenceError("Le token Confluence est vide (CONFLUENCE_TOKEN).")
    return site


Opener = Callable[[urllib.request.Request], "tuple[int, Mapping[str, str], bytes]"]


def _urlopen(request: urllib.request.Request) -> tuple[int, Mapping[str, str], bytes]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310 - https, checked()
            return answer.status, dict(answer.headers), answer.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()


class Client:
    """Confluence's REST API, read only: GET, again when it asks to wait."""

    def __init__(self, site: Site, opener: Opener | None = None, *, pause: float = 1.0) -> None:
        self.site = checked(site)
        self._open = opener or _urlopen
        self._pause = pause

    def _url(self, path: str, params: Mapping[str, object] | None = None) -> str:
        url = self.site.base + (path if path.startswith("/") else f"/{path}")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def get(self, path: str, params: Mapping[str, object] | None = None) -> Any:
        url = self._url(path, params)
        headers = {"Authorization": self.site.authorization, "Accept": "application/json"}
        for attempt in range(RETRIES):
            request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
            try:
                status, answered, payload = self._open(request)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == RETRIES - 1:
                    raise ConfluenceError(f"Confluence ne répond pas ({error}).") from None
                time.sleep(self._pause * (attempt + 1))
                continue
            if status in (429, 502, 503, 504) and attempt < RETRIES - 1:
                wait = float(answered.get("Retry-After") or self._pause * (attempt + 1))
                time.sleep(min(wait, 60.0))
                continue
            if status == 404:
                return None
            if status in (401, 403):
                raise ConfluenceError(
                    f"Confluence refuse l'accès ({status}) : vérifiez l'adresse e-mail, le token, "
                    "et les droits du compte sur cet espace."
                )
            if status >= 400:
                raise ConfluenceError(f"Confluence a répondu {status}.")
            return json.loads(payload) if payload else {}
        raise ConfluenceError("Confluence ne répond pas.")

    def each(self, path: str, params: Mapping[str, object]) -> Iterator[dict[str, Any]]:
        start = 0
        while True:
            found = self.get(path, {**params, "start": start, "limit": PAGE_SIZE}) or {}
            results = found.get("results") or []
            yield from results
            if not results or (
                len(results) < PAGE_SIZE and not found.get("_links", {}).get("next")
            ):
                return
            start += len(results)


# ── the storage format, as text ─────────────────────────────────────────────

_BLOCK = re.compile(r"</?(p|div|h[1-6]|li|tr|br|table|ul|ol|blockquote|pre)\b[^>]*>", re.IGNORECASE)
_CELL = re.compile(r"</t[dh]>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)


def text_of(storage: str) -> str:
    """A page's storage format as text: its headings marked, its blocks on
    their lines, its table cells apart, its code kept."""
    said = _CDATA.sub(lambda m: m.group(1), storage)
    said = _HEADING.sub(lambda m: f"\n{'#' * int(m.group(1))} {m.group(2)}\n", said)
    said = _CELL.sub(" | ", said)
    said = _BLOCK.sub("\n", said)
    said = _TAG.sub("", said)
    said = html.unescape(said)
    lines = [" ".join(line.split()) for line in said.splitlines()]
    return "\n".join(line for line in lines if line)


def _page(item: Mapping[str, Any], site: Site, space: str) -> Page:
    ancestors = item.get("ancestors") or []
    version = item.get("version") or {}
    return Page(
        id=str(item["id"]),
        title=str(item.get("title") or ""),
        text=text_of(str(((item.get("body") or {}).get("storage") or {}).get("value") or "")),
        url=site.page_url(str(item["id"])),
        parent_id=str(ancestors[-1]["id"]) if ancestors else None,
        space=space,
        updated_at=str(version.get("when") or ""),
    )


def read_space(client: Client, key: str, *, root: str | None = None) -> list[Page]:
    """A space's current pages — or `root` and every page under it."""
    space = client.get(f"/rest/api/space/{urllib.parse.quote(key)}")
    if space is None:
        raise ConfluenceError(f"L'espace {key} est introuvable, ou ce compte ne peut pas le lire.")
    if root:
        first = client.get(f"/rest/api/content/{urllib.parse.quote(root)}", {"expand": EXPAND})
        if first is None:
            raise ConfluenceError(
                f"La page {root} est introuvable, ou ce compte ne peut pas la lire."
            )
        items = [
            first,
            *client.each(
                f"/rest/api/content/{urllib.parse.quote(root)}/descendant/page", {"expand": EXPAND}
            ),
        ]
    else:
        items = list(
            client.each(
                "/rest/api/content",
                {"spaceKey": key, "type": "page", "status": "current", "expand": EXPAND},
            )
        )
    pages = [_page(item, client.site, key) for item in items]
    if root and pages:
        # The root at the top of what is read.
        pages[0] = Page(**{**pages[0].__dict__, "parent_id": None})
    return pages


def list_spaces(client: Client) -> list[dict[str, str]]:
    return [
        {"key": str(s.get("key")), "name": str(s.get("name") or s.get("key"))}
        for s in client.each("/rest/api/space", {"type": "global"})
    ]


# ── a folder ─────────────────────────────────────────────────────────────────


def read_folder(folder: Path) -> list[Page]:
    """A folder: an export of the copy tool (space.json, pages/<id>/), or
    Markdown and HTML files whose folders are their parent pages."""
    meta = folder / "space.json"
    if meta.is_file():
        said = json.loads(meta.read_text(encoding="utf-8"))
        key = str(said.get("key") or "")
        site = Site(url=str(said.get("site") or ""), token="-") if said.get("site") else None  # noqa: S106
        pages: list[Page] = []
        for page_json in sorted((folder / "pages").glob("*/page.json")):
            item = json.loads(page_json.read_text(encoding="utf-8"))
            body = page_json.parent / "body.xml"
            page_id = str(item["id"])
            pages.append(
                Page(
                    id=page_id,
                    title=str(item.get("title") or page_id),
                    text=text_of(body.read_text(encoding="utf-8")) if body.is_file() else "",
                    url=site.page_url(page_id) if site else "",
                    parent_id=item.get("parent_id"),
                    space=key,
                )
            )
        return pages
    return list(_files(folder, None, folder))


def _title(name: str) -> str:
    return re.sub(r"^\d+[\s._-]+", "", name).replace("_", " ").strip() or name


def _file_page(path: Path, parent: str | None, top: Path) -> Page:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = _title(path.stem)
    if path.suffix.lower() == ".md":
        first = text.lstrip().split("\n", 1)[0]
        if first.startswith("# "):
            title = first[2:].strip() or title
    else:
        found = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        if found and found.group(1).strip():
            title = html.unescape(found.group(1).strip())
        main = re.search(r'<div[^>]*id="main-content"[^>]*>(.*?)</div>\s*</div>', text, re.DOTALL)
        text = text_of(main.group(1) if main else text)
    return Page(id=str(path.relative_to(top)), title=title, text=text, parent_id=parent)


def _files(folder: Path, parent: str | None, top: Path) -> Iterator[Page]:
    entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    files = {p.stem: p for p in entries if p.suffix.lower() in (".md", ".html", ".htm")}
    for entry in entries:
        if entry.is_dir():
            own = files.pop(entry.name, None)
            page = (
                _file_page(own, parent, top)
                if own
                else Page(
                    id=str(entry.relative_to(top)), title=_title(entry.name), parent_id=parent
                )
            )
            yield page
            yield from _files(entry, page.id, top)
    for stem in sorted(files):
        yield _file_page(files[stem], parent, top)


__all__ = [
    "Client",
    "ConfluenceError",
    "Site",
    "checked",
    "list_spaces",
    "read_folder",
    "read_space",
    "text_of",
]
