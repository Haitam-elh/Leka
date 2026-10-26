"""Copier un espace Confluence — son arborescence, ses pages, leurs pièces
jointes — dans un autre Confluence. Hors de LEKA : un seul fichier, Python 3.9
ou plus, aucune dépendance à installer.

    python confluence_copy.py copy   --space CLE [--root-page ID] [--target-space CLE] [--dry-run]
    python confluence_copy.py export --space CLE [--root-page ID] --out ./export
    python confluence_copy.py import --from ./export [--target-space CLE] [--dry-run]

    copy     lit le Confluence source et écrit dans le Confluence cible, page
             par page, les parents avant les enfants
    export   lit le Confluence source et écrit un dossier local — à zipper et
             transmettre : la cible n'est jamais touchée, et celui qui exporte
             n'a pas besoin de ses identifiants
    import   écrit dans la cible un dossier : un export de cet outil, ou un
             dossier de fichiers Markdown (.md) ou HTML (.html) dont
             l'arborescence des dossiers est celle des pages

La source : Confluence Cloud (https://<site>.atlassian.net) ou Data Center
(https://confluence.<entreprise>.com) — son API REST, la même pour les deux.
La cible : Confluence Cloud.

Les identifiants sont dans un fichier .env à côté de cet outil, ou dans
l'environnement — jamais dans une commande, jamais affichés :

    SOURCE_URL, SOURCE_EMAIL, SOURCE_TOKEN   le Confluence lu
    TARGET_URL, TARGET_EMAIL, TARGET_TOKEN   le Confluence écrit

Cloud : le mail du compte et un token API (id.atlassian.com → Sécurité →
Tokens d'API). Data Center : un jeton d'accès personnel, mail laissé vide.

Ce qu'il garantit :
- `--dry-run` affiche l'arbre qui serait créé, et n'écrit rien ;
- relancé, il ne crée aucun doublon : une page déjà là — même espace, même
  titre — est mise à jour si elle a changé, ignorée sinon ; une pièce jointe
  déjà là n'est pas renvoyée ;
- les liens d'une page vers une autre page copiée mènent à sa copie ;
- à la fin, un rapport : pages créées, mises à jour, ignorées, en erreur —
  affiché, et écrit dans rapport-copie.json.

Il ne lit que la source, n'écrit que dans la cible : rien d'autre n'est
contacté, rien n'est envoyé ailleurs.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

PAGE_SIZE = 50
# Une pièce jointe plus lourde n'est pas copiée : elle est dite dans le rapport.
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
TIMEOUT = 60
RETRIES = 5
REPORT = "rapport-copie.json"
HERE = Path(__file__).resolve().parent


class CopyError(Exception):
    """Ce qui arrête l'outil : une configuration manquante, un accès refusé."""


# ── configuration ──────────────────────────────────────────────────────────


def load_env(path: Path) -> None:
    """Les variables d'un fichier .env, sans écraser celles déjà définies."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Site:
    """Un Confluence, et comment s'y présenter."""

    url: str
    email: str
    token: str = field(repr=False)

    @property
    def cloud(self) -> bool:
        return ".atlassian.net" in urllib.parse.urlsplit(self.url).netloc

    @property
    def base(self) -> str:
        """Où commence son API : /wiki sur Cloud, l'adresse donnée sinon."""
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


def site_from_env(prefix: str) -> Site:
    url = os.environ.get(f"{prefix}_URL", "").strip()
    token = os.environ.get(f"{prefix}_TOKEN", "").strip()
    if not url or not token:
        raise CopyError(
            f"{prefix}_URL et {prefix}_TOKEN sont à renseigner dans le fichier .env "
            "(voir .env.example)."
        )
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        raise CopyError(f"{prefix}_URL doit commencer par https://.")
    return Site(url=url, email=os.environ.get(f"{prefix}_EMAIL", "").strip(), token=token)


# ── HTTP ───────────────────────────────────────────────────────────────────

# Ce qui envoie une requête : urllib, remplacé dans les tests.
Opener = Callable[[urllib.request.Request], tuple[int, Mapping[str, str], bytes]]


def _urlopen(request: urllib.request.Request) -> tuple[int, Mapping[str, str], bytes]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310
            return answer.status, dict(answer.headers), answer.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()


class Client:
    """Un Confluence, par son API REST : lire, écrire, en reprenant quand il
    demande d'attendre. Le token n'apparaît jamais dans un message."""

    def __init__(self, site: Site, opener: Opener = _urlopen, *, pause: float = 1.0) -> None:
        self.site = site
        self._open = opener
        self._pause = pause

    def url(self, path: str, params: Mapping[str, object] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            full = path
        else:
            full = self.site.base + (path if path.startswith("/") else f"/{path}")
        if params:
            full += ("&" if "?" in full else "?") + urllib.parse.urlencode(params)
        return full

    def call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        body: object = None,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        sent = {"Authorization": self.site.authorization, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        url = self.url(path, params)
        for attempt in range(RETRIES):
            # https only: site_from_env refuses any other scheme.
            request = urllib.request.Request(url, data=data, headers=sent, method=method)  # noqa: S310
            try:
                status, answered, payload = self._open(request)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == RETRIES - 1:
                    raise CopyError(f"{method} {self._said(url)} : {error}") from None
                time.sleep(self._pause * (attempt + 1))
                continue
            if status in (429, 502, 503, 504) and attempt < RETRIES - 1:
                wait = float(dict(answered).get("Retry-After") or self._pause * (attempt + 1))
                time.sleep(min(wait, 60.0))
                continue
            if status == 404:
                return None
            if status in (401, 403):
                raise CopyError(
                    f"Accès refusé par {urllib.parse.urlsplit(url).netloc} ({status}) : "
                    "vérifiez le mail et le token, et les droits du compte sur cet espace."
                )
            if status >= 400:
                said = payload[:300].decode("utf-8", "replace")
                raise CopyError(f"{method} {self._said(url)} : {status} {said}")
            if raw:
                return payload
            return json.loads(payload) if payload else {}
        raise CopyError(f"{method} {self._said(url)} : le site ne répond pas.")

    def _said(self, url: str) -> str:
        """Une adresse telle qu'on peut la montrer : sans le token."""
        return url.replace(self.site.token, "***")

    def each(self, path: str, params: Mapping[str, object]) -> Iterator[dict[str, Any]]:
        """Chaque résultat d'une liste, page après page."""
        start = 0
        while True:
            found = self.call("GET", path, params={**params, "start": start, "limit": PAGE_SIZE})
            results = (found or {}).get("results") or []
            yield from results
            if len(results) < PAGE_SIZE and not (found or {}).get("_links", {}).get("next"):
                return
            start += len(results)
            if not results:
                return


# ── what is copied ─────────────────────────────────────────────────────────


@dataclass
class Attachment:
    title: str
    media_type: str
    size: int
    download: str = ""
    data: bytes | None = None


@dataclass
class Page:
    id: str
    title: str
    parent_id: str | None
    body: str
    position: int = 0
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class Space:
    key: str
    name: str
    pages: list[Page]
    # Where it was read: its pages' addresses, rewritten to their copies'.
    site: str = ""

    def ordered(self) -> list[Page]:
        """Les parents avant les enfants, chaque fratrie dans son ordre."""
        known = {p.id for p in self.pages}
        children: dict[str | None, list[Page]] = {}
        for page in self.pages:
            parent = page.parent_id if page.parent_id in known else None
            children.setdefault(parent, []).append(page)
        out: list[Page] = []

        def walk(parent: str | None) -> None:
            for page in sorted(children.get(parent, []), key=lambda p: (p.position, p.title)):
                out.append(page)
                walk(page.id)

        walk(None)
        return out

    def depth_of(self, page: Page) -> int:
        by_id = {p.id: p for p in self.pages}
        depth, current = 0, page
        while current.parent_id in by_id and depth < 100:
            current = by_id[str(current.parent_id)]
            depth += 1
        return depth


# ── reading the source ─────────────────────────────────────────────────────

EXPAND = "ancestors,version,body.storage,extensions.position"


def _page(item: Mapping[str, Any]) -> Page:
    ancestors = item.get("ancestors") or []
    position = (item.get("extensions") or {}).get("position")
    return Page(
        id=str(item["id"]),
        title=str(item.get("title") or ""),
        parent_id=str(ancestors[-1]["id"]) if ancestors else None,
        body=str(((item.get("body") or {}).get("storage") or {}).get("value") or ""),
        position=int(position) if isinstance(position, int) else 0,
    )


def read_space(
    client: Client, key: str, *, root: str | None = None, attachments: bool = True
) -> Space:
    """Un espace — ou une page et ses descendantes —, ses pages et leurs
    pièces jointes."""
    space = client.call("GET", f"/rest/api/space/{urllib.parse.quote(key)}")
    if space is None:
        raise CopyError(f"L'espace {key} est introuvable, ou ce compte ne peut pas le lire.")
    if root:
        first = client.call("GET", f"/rest/api/content/{root}", params={"expand": EXPAND})
        if first is None:
            raise CopyError(f"La page {root} est introuvable, ou ce compte ne peut pas la lire.")
        items = [
            first,
            *client.each(f"/rest/api/content/{root}/descendant/page", {"expand": EXPAND}),
        ]
    else:
        items = list(
            client.each(
                "/rest/api/content",
                {"spaceKey": key, "type": "page", "status": "current", "expand": EXPAND},
            )
        )
    pages = [_page(item) for item in items]
    if root:
        # La page racine en tête de l'arbre copié.
        pages[0].parent_id = None
    if attachments:
        for page in pages:
            page.attachments = list(_attachments(client, page.id))
    return Space(key=key, name=str(space.get("name") or key), pages=pages, site=client.site.base)


def _attachments(client: Client, page_id: str) -> Iterator[Attachment]:
    for item in client.each(f"/rest/api/content/{page_id}/child/attachment", {}):
        size = int(((item.get("extensions") or {}).get("fileSize")) or 0)
        yield Attachment(
            title=str(item.get("title") or ""),
            media_type=str(
                ((item.get("metadata") or {}).get("mediaType"))
                or (item.get("extensions") or {}).get("mediaType")
                or "application/octet-stream"
            ),
            size=size,
            download=str((item.get("_links") or {}).get("download") or ""),
        )


def fetch(client: Client, attachment: Attachment) -> bytes | None:
    """Ses octets — None quand elle est trop lourde pour être copiée."""
    if attachment.data is not None:
        return attachment.data
    if attachment.size > MAX_ATTACHMENT_BYTES or not attachment.download:
        return None
    data = client.call("GET", attachment.download, raw=True)
    return data if isinstance(data, bytes) else None


# ── writing the target ─────────────────────────────────────────────────────


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    attachments: int = 0
    attachments_skipped: list[str] = field(default_factory=list)

    def said(self) -> str:
        lines = [
            f"Pages créées        : {len(self.created)}",
            f"Pages mises à jour  : {len(self.updated)}",
            f"Pages ignorées      : {len(self.skipped)} (déjà identiques)",
            f"Pages en erreur     : {len(self.failed)}",
            f"Pièces jointes      : {self.attachments} copiées"
            + (
                f", {len(self.attachments_skipped)} non copiées" if self.attachments_skipped else ""
            ),
        ]
        lines += [f"  ✗ {f['title']} : {f['error']}" for f in self.failed]
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        return {
            "créées": self.created,
            "mises_à_jour": self.updated,
            "ignorées": self.skipped,
            "en_erreur": self.failed,
            "pièces_jointes": self.attachments,
            "pièces_jointes_non_copiées": self.attachments_skipped,
        }


_SPACE_KEY = re.compile(r'(ri:space-key=")([^"]*)(")')
# A page's address: …/spaces/KEY/pages/ID…, …/pages/viewpage.action?pageId=ID.
_ADDRESS = (
    r"(?P<path>/spaces/[^/\"'\s<>]+/pages/|/pages/viewpage\.action\?pageId=|/pages/)(?P<id>\d+)"
)


def rewritten(
    body: str,
    source_key: str,
    target_key: str,
    ids: Mapping[str, str],
    *,
    source_site: str = "",
    target_site: str = "",
) -> str:
    """Une page dont les liens vers l'espace copié mènent à sa copie : la clé
    d'espace des liens Confluence, et l'adresse entière des liens vers une
    page copiée — le site, l'espace et l'identifiant de la copie."""

    def space(match: re.Match[str]) -> str:
        key = target_key if match.group(2) == source_key else match.group(2)
        return f"{match.group(1)}{key}{match.group(3)}"

    said = _SPACE_KEY.sub(space, body)
    if not ids or not target_site:
        return said
    prefix = f"(?:{re.escape(source_site)})?" if source_site else ""
    pattern = re.compile(prefix + _ADDRESS)

    def page(match: re.Match[str]) -> str:
        new = ids.get(match.group("id"))
        if new is None:
            return match.group(0)
        return f"{target_site}/spaces/{target_key}/pages/{new}"

    return pattern.sub(page, said)


def _normal(body: str) -> str:
    return re.sub(r"\s+", " ", body).strip()


class Writer:
    """La cible : un espace de Confluence Cloud, ses pages écrites une à une,
    sans doublon."""

    def __init__(self, client: Client, key: str) -> None:
        self.client = client
        self.key = key

    def ensure_space(self, name: str) -> None:
        if self.client.call("GET", f"/rest/api/space/{urllib.parse.quote(self.key)}") is not None:
            return
        try:
            self.client.call("POST", "/rest/api/space", body={"key": self.key, "name": name})
        except CopyError as error:
            raise CopyError(
                f"L'espace {self.key} n'existe pas dans la cible et n'a pas pu être créé "
                f"({error}). Créez-le à la main dans Confluence, avec cette clé, puis relancez."
            ) from None

    def existing(self, title: str) -> dict[str, Any] | None:
        found = self.client.call(
            "GET",
            "/rest/api/content",
            params={
                "spaceKey": self.key,
                "title": title,
                "type": "page",
                "expand": "version,body.storage,ancestors",
            },
        )
        results = (found or {}).get("results") or []
        return results[0] if results else None

    def put(self, page: Page, body: str, parent: str | None, report: Report) -> str:
        """La page écrite sous son parent — créée, mise à jour, ou ignorée si
        elle y est déjà telle quelle. Son identifiant dans la cible."""
        there = self.existing(page.title)
        ancestors = [{"id": parent}] if parent else []
        if there is not None:
            same_body = _normal(((there.get("body") or {}).get("storage") or {}).get("value") or "")
            had = there.get("ancestors") or []
            same_parent = (str(had[-1]["id"]) if had else None) == parent
            if same_body == _normal(body) and same_parent:
                report.skipped.append(page.title)
                return str(there["id"])
            version = int(((there.get("version") or {}).get("number")) or 1)
            self.client.call(
                "PUT",
                f"/rest/api/content/{there['id']}",
                body={
                    "id": str(there["id"]),
                    "type": "page",
                    "title": page.title,
                    "space": {"key": self.key},
                    "ancestors": ancestors,
                    "version": {"number": version + 1},
                    "body": {"storage": {"value": body, "representation": "storage"}},
                },
            )
            report.updated.append(page.title)
            return str(there["id"])
        made = self.client.call(
            "POST",
            "/rest/api/content",
            body={
                "type": "page",
                "title": page.title,
                "space": {"key": self.key},
                "ancestors": ancestors,
                "body": {"storage": {"value": body, "representation": "storage"}},
            },
        )
        report.created.append(page.title)
        return str(made["id"])

    def attach(self, page_id: str, attachment: Attachment, data: bytes, report: Report) -> None:
        """Une pièce jointe, envoyée sauf si la page l'a déjà."""
        had = self.client.call(
            "GET",
            f"/rest/api/content/{page_id}/child/attachment",
            params={"filename": attachment.title},
        )
        if (had or {}).get("results"):
            return
        boundary = uuid.uuid4().hex
        name = attachment.title.replace('"', "")
        payload = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{name}"\r\nContent-Type: {attachment.media_type}\r\n\r\n'
            ).encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        self.client.call(
            "POST",
            f"/rest/api/content/{page_id}/child/attachment",
            data=payload,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-Atlassian-Token": "no-check",
            },
        )
        report.attachments += 1


def write(
    space: Space,
    writer: Writer,
    *,
    source: Client | None,
    report: Report,
    say: Callable[[str], None] = print,
) -> Report:
    """Un espace lu, écrit dans la cible : les pages dans l'ordre de leur
    arbre, puis leurs liens réécrits vers leurs copies."""
    writer.ensure_space(space.name)
    # What the target already has: links lead there from the first write —
    # and a run again rewrites nothing.
    ids: dict[str, str] = {}
    for page in space.pages:
        there = writer.existing(page.title)
        if there is not None:
            ids[page.id] = str(there["id"])
    bodies: dict[str, str] = {}
    for page in space.ordered():
        depth = space.depth_of(page)
        say(f"{'  ' * depth}• {page.title}")
        parent = ids.get(page.parent_id or "")
        if page.parent_id and parent is None:
            report.failed.append(
                {"title": page.title, "error": "sa page parente n'a pas été copiée"}
            )
            continue
        body = rewritten(
            page.body,
            space.key,
            writer.key,
            ids,
            source_site=space.site,
            target_site=writer.client.site.base,
        )
        try:
            target = writer.put(page, body, parent, report)
        except CopyError as error:
            report.failed.append({"title": page.title, "error": str(error)})
            continue
        ids[page.id] = target
        bodies[page.id] = body
        for attachment in page.attachments:
            try:
                data = fetch(source, attachment) if source is not None else attachment.data
                if data is None:
                    report.attachments_skipped.append(f"{page.title} / {attachment.title}")
                    continue
                writer.attach(target, attachment, data, report)
            except CopyError as error:
                report.attachments_skipped.append(f"{page.title} / {attachment.title} ({error})")
    # Les liens par adresse vers une page copiée : vers sa copie.
    for page in space.pages:
        if page.id not in ids:
            continue
        linked = rewritten(
            page.body,
            space.key,
            writer.key,
            ids,
            source_site=space.site,
            target_site=writer.client.site.base,
        )
        if linked != bodies[page.id]:
            try:
                writer.put(page, linked, ids.get(page.parent_id or ""), Report())
            except CopyError as error:
                report.failed.append({"title": page.title, "error": f"liens : {error}"})
    return report


# ── a local folder: an export, or Markdown and HTML files ──────────────────


def export(space: Space, source: Client, out: Path, say: Callable[[str], None] = print) -> None:
    """L'espace lu, écrit dans un dossier : space.json, puis une page par
    dossier — page.json, body.xml et ses pièces jointes."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "space.json").write_text(
        json.dumps(
            {"key": space.key, "name": space.name, "site": space.site},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tree: list[str] = []
    for page in space.ordered():
        folder = out / "pages" / page.id
        (folder / "attachments").mkdir(parents=True, exist_ok=True)
        (folder / "body.xml").write_text(page.body, encoding="utf-8")
        files = []
        for attachment in page.attachments:
            data = fetch(source, attachment)
            if data is None:
                continue
            name = re.sub(r"[\\/:*?\"<>|]", "_", attachment.title)
            (folder / "attachments" / name).write_bytes(data)
            files.append(
                {"title": attachment.title, "file": name, "media_type": attachment.media_type}
            )
        (folder / "page.json").write_text(
            json.dumps(
                {
                    "id": page.id,
                    "title": page.title,
                    "parent_id": page.parent_id,
                    "position": page.position,
                    "attachments": files,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tree.append(f"{'  ' * space.depth_of(page)}{page.title}")
        say(tree[-1])
    (out / "arborescence.txt").write_text("\n".join(tree) + "\n", encoding="utf-8")


def read_folder(folder: Path) -> Space:
    """Un dossier : un export de cet outil, ou des fichiers Markdown et HTML
    dont les dossiers sont les pages parentes."""
    meta = folder / "space.json"
    if meta.is_file():
        said = json.loads(meta.read_text(encoding="utf-8"))
        pages: list[Page] = []
        for page_json in sorted((folder / "pages").glob("*/page.json")):
            item = json.loads(page_json.read_text(encoding="utf-8"))
            here = page_json.parent
            pages.append(
                Page(
                    id=str(item["id"]),
                    title=str(item["title"]),
                    parent_id=item.get("parent_id"),
                    body=(here / "body.xml").read_text(encoding="utf-8"),
                    position=int(item.get("position") or 0),
                    attachments=[
                        Attachment(
                            title=str(a["title"]),
                            media_type=str(a.get("media_type") or "application/octet-stream"),
                            size=(here / "attachments" / a["file"]).stat().st_size,
                            data=(here / "attachments" / a["file"]).read_bytes(),
                        )
                        for a in item.get("attachments") or []
                        if (here / "attachments" / a["file"]).is_file()
                    ],
                )
            )
        return Space(
            key=str(said["key"]),
            name=str(said.get("name") or said["key"]),
            pages=pages,
            site=str(said.get("site") or ""),
        )
    return Space(key="", name=folder.name, pages=list(_files(folder, None)))


def _files(folder: Path, parent: str | None) -> Iterator[Page]:
    """Chaque fichier .md ou .html d'un dossier, une page ; chaque sous-dossier,
    la page qui porte son nom — ou une page vide à son nom —, parente de ce
    qu'il contient."""
    entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    files = {p.stem: p for p in entries if p.suffix.lower() in (".md", ".html", ".htm")}
    for position, entry in enumerate(entries):
        if entry.is_dir():
            own = files.pop(entry.name, None)
            page = _file_page(own, parent, position) if own else None
            if page is None:
                page = Page(
                    id=f"dir:{entry}",
                    title=_title(entry.name),
                    parent_id=parent,
                    body="",
                    position=position,
                )
            yield page
            yield from _files(entry, page.id)
    for position, stem in enumerate(sorted(files)):
        page = _file_page(files[stem], parent, position)
        if page is not None:
            yield page


def _title(name: str) -> str:
    return re.sub(r"^\d+[\s._-]+", "", name).replace("_", " ").strip() or name


def _file_page(path: Path, parent: str | None, position: int) -> Page | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".md":
        title, body = markdown_page(text, _title(path.stem))
    else:
        title, body = html_page(text, _title(path.stem))
    return Page(id=f"file:{path}", title=title, parent_id=parent, body=body, position=position)


def _inline(text: str) -> str:
    said = html.escape(text, quote=False)
    said = re.sub(r"`([^`]+)`", r"<code>\1</code>", said)
    said = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", said)
    said = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", said)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', said)


def markdown_page(text: str, fallback: str) -> tuple[str, str]:
    """Un fichier Markdown : son titre (son premier titre de niveau 1, sinon
    le nom du fichier) et son corps au format de stockage de Confluence."""
    lines = text.replace("\r\n", "\n").split("\n")
    title = fallback
    if lines and lines[0].startswith("# "):
        title = lines.pop(0)[2:].strip() or fallback
    out: list[str] = []
    paragraph: list[str] = []
    listing: list[str] = []
    ordered = False
    i = 0

    def flush() -> None:
        nonlocal listing
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if listing:
            tag = "ol" if ordered else "ul"
            out.append(
                f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in listing) + f"</{tag}>"
            )
            listing = []

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            value = "\n".join(code).replace("]]>", "]]]]><![CDATA[>")
            out.append(
                '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
                f"<![CDATA[{value}]]></ac:plain-text-body></ac:structured-macro>"
            )
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        number = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\s*\|?\s*:?-+", lines[i + 1])
        ):
            flush()
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = ["<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>"]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("<table><tbody>" + "".join(rows) + "</tbody></table>")
            continue
        elif bullet or number:
            if paragraph:
                flush()
            if listing and ordered != bool(number):
                flush()
            ordered = bool(number)
            listing.append((number or bullet).group(1))  # type: ignore[union-attr]
        elif not line.strip():
            flush()
        else:
            if listing:
                flush()
            paragraph.append(line.strip())
        i += 1
    flush()
    return title, "".join(out)


# What Confluence's storage format accepts as it is: well-formed XHTML.
_VOID = frozenset({"br", "hr", "img", "col", "input", "meta", "link", "area", "source"})
_DROPPED = frozenset({"script", "style", "head", "title", "nav", "header", "footer", "noscript"})


class _Xhtml(HTMLParser):
    """Un fichier HTML réécrit en XHTML bien formé : ses balises fermées, ses
    scripts et styles retirés — le contenu de son corps seulement."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.dropping = 0
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag in _DROPPED:
            self.dropping += 1
            return
        if self.dropping or tag in ("html", "body"):
            return
        said = "".join(
            f' {name}="{html.escape(value or "", quote=True)}"'
            for name, value in attrs
            if not name.startswith("on")
            and name in ("href", "src", "alt", "title", "colspan", "rowspan")
        )
        if tag in _VOID:
            self.out.append(f"<{tag}{said} />")
            return
        self.out.append(f"<{tag}{said}>")
        self.open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in _DROPPED:
            self.dropping = max(0, self.dropping - 1)
            return
        if self.dropping or tag in _VOID or tag not in self.open:
            return
        while self.open:
            last = self.open.pop()
            self.out.append(f"</{last}>")
            if last == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if not self.dropping:
            self.out.append(html.escape(data, quote=False))

    def body(self) -> str:
        return "".join(self.out) + "".join(f"</{t}>" for t in reversed(self.open))


def html_page(text: str, fallback: str) -> tuple[str, str]:
    """Un fichier HTML — d'un export Confluence, ou écrit à la main — : son
    titre et son corps en XHTML. D'un export Confluence, le contenu de la page
    seulement (main-content), sans le fil d'Ariane ni le pied de page."""
    main = re.search(
        r'<div[^>]+id="main-content"[^>]*>(.*?)</div>\s*(?:<div[^>]+id="footer"|</body>)',
        text,
        re.S,
    )
    parser = _Xhtml()
    parser.feed(text if main is None else main.group(1))
    parser.close()
    whole = _Xhtml()
    whole.feed(text)
    title = re.sub(r"\s+", " ", whole.title).strip()
    title = re.sub(r"^[^:]+ : ", "", title) or fallback
    return title, parser.body()


# ── the command ────────────────────────────────────────────────────────────


def _tree(space: Space, say: Callable[[str], None]) -> None:
    pages = space.ordered()
    depth = max((space.depth_of(p) for p in pages), default=-1) + 1
    files = sum(len(p.attachments) for p in pages)
    for page in pages:
        extra = f"  ({len(page.attachments)} pièce(s) jointe(s))" if page.attachments else ""
        say(f"{'  ' * space.depth_of(page)}• {page.title}{extra}")
    say(f"\n{len(pages)} pages, {depth} niveau(x), {files} pièce(s) jointe(s).")


def main(
    argv: Sequence[str] | None = None,
    *,
    opener: Opener = _urlopen,
    say: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(
        prog="confluence_copy",
        description="Copier l'arborescence d'un espace Confluence dans un autre Confluence.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helped in (
        ("copy", "lire la source et écrire dans la cible"),
        ("export", "lire la source et écrire un dossier local"),
    ):
        command = sub.add_parser(name, help=helped)
        command.add_argument("--space", required=True, help="la clé de l'espace source, ex. ARCHI")
        command.add_argument(
            "--root-page", help="l'identifiant d'une page : elle et ses enfants seulement"
        )
        command.add_argument(
            "--no-attachments", action="store_true", help="sans les pièces jointes"
        )
        if name == "copy":
            command.add_argument(
                "--target-space", help="la clé de l'espace cible ; par défaut celle de la source"
            )
            command.add_argument(
                "--dry-run", action="store_true", help="afficher l'arbre, ne rien écrire"
            )
        else:
            command.add_argument("--out", required=True, help="le dossier où écrire l'export")
    imported = sub.add_parser("import", help="écrire un dossier local dans la cible")
    imported.add_argument("--from", dest="folder", required=True, help="le dossier à importer")
    imported.add_argument("--target-space", help="la clé de l'espace cible")
    imported.add_argument("--dry-run", action="store_true", help="afficher l'arbre, ne rien écrire")
    imported.add_argument("--space-name", help="le nom de l'espace cible, s'il faut le créer")
    args = parser.parse_args(argv)

    load_env(HERE / ".env")
    load_env(Path.cwd() / ".env")
    try:
        if args.command in ("copy", "export"):
            source = Client(site_from_env("SOURCE"), opener)
            say(f"Lecture de l'espace {args.space}…")
            space = read_space(
                source, args.space, root=args.root_page, attachments=not args.no_attachments
            )
            if args.command == "export":
                export(space, source, Path(args.out), say=lambda _line: None)
                _tree(space, say)
                say(f"\nExport écrit dans {Path(args.out).resolve()}")
                return 0
        else:
            source = None
            space = read_folder(Path(args.folder))
            if not space.pages:
                raise CopyError(f"Aucune page dans {args.folder}.")
        key = args.target_space or space.key
        if not key:
            raise CopyError("--target-space est requis : le dossier importé ne dit pas d'espace.")
        if args.command == "import" and args.space_name:
            space.name = args.space_name
        if args.dry_run:
            say("Ce qui sera créé dans la cible (rien n'est écrit) :\n")
            _tree(space, say)
            return 0
        writer = Writer(Client(site_from_env("TARGET"), opener), key)
        say(f"Écriture dans l'espace {key}…\n")
        report = write(space, writer, source=source, report=Report(), say=say)
        Path(REPORT).write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        say("\n" + report.said())
        say(f"\nRapport : {Path(REPORT).resolve()}")
        return 1 if report.failed else 0
    except CopyError as error:
        say(f"Erreur : {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
