"""Confluence pages as the architect reads them: one page, its place in its
space's tree, its text — wherever it was read from (the platform's synced
Confluence, Confluence's API, an export on disk).

    Page       one page: its id, title, link, parent, space, last change, text
    Tree       a space's pages as Confluence holds them: children by parent,
               each page's depth, a page and everything under it

Nothing here reads or writes anything: the readers (confluence.py, and the
platform's) build pages; the analysis reads them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    text: str = ""
    url: str = ""
    parent_id: str | None = None
    space: str = ""
    updated_at: str = ""


@dataclass
class Node:
    page: Page
    depth: int = 0
    children: list[Node] = field(default_factory=list)


class Tree:
    """A space's pages, as their parents hold them. A page whose parent is
    not among them is a root: the space's home, or the top of what was read."""

    def __init__(self, pages: Iterable[Page]) -> None:
        self.pages: dict[str, Page] = {}
        for page in pages:
            self.pages.setdefault(page.id, page)
        self.children: dict[str | None, list[Page]] = {}
        for page in self.pages.values():
            parent = page.parent_id if page.parent_id in self.pages else None
            self.children.setdefault(parent, []).append(page)
        for siblings in self.children.values():
            siblings.sort(key=lambda p: p.title.lower())

    @property
    def roots(self) -> list[Page]:
        return list(self.children.get(None, []))

    def under(self, root: str | None) -> list[Page]:
        """`root` and every page under it, in reading order — every page
        when `root` is None. A page never read twice, whatever its links."""
        start = [self.pages[root]] if root is not None and root in self.pages else []
        if root is None:
            start = self.roots
        found: list[Page] = []
        seen: set[str] = set()
        stack = list(reversed(start))
        while stack:
            page = stack.pop()
            if page.id in seen:
                continue
            seen.add(page.id)
            found.append(page)
            stack.extend(reversed(self.children.get(page.id, [])))
        return found

    def nodes(self, root: str | None = None) -> list[Node]:
        """The tree itself, each page with its depth — from `root`, or from
        the space's roots."""
        seen: set[str] = set()

        def grow(page: Page, depth: int) -> Node:
            seen.add(page.id)
            node = Node(page, depth)
            for child in self.children.get(page.id, []):
                if child.id not in seen:
                    node.children.append(grow(child, depth + 1))
            return node

        tops = [self.pages[root]] if root is not None and root in self.pages else self.roots
        return [grow(page, 0) for page in tops]

    def depth(self, root: str | None = None) -> int:
        """How deep it goes: 1 for pages without children."""

        def deepest(nodes: Sequence[Node]) -> int:
            return max((1 + deepest(n.children) for n in nodes), default=0)

        return deepest(self.nodes(root))

    def path(self, page_id: str) -> list[str]:
        """Its titles from the top: where it sits, as a reader says it."""
        titles: list[str] = []
        seen: set[str] = set()
        current = self.pages.get(page_id)
        while current is not None and current.id not in seen:
            seen.add(current.id)
            titles.append(current.title)
            current = self.pages.get(current.parent_id or "")
        return list(reversed(titles))

    def __iter__(self) -> Iterator[Page]:
        return iter(self.pages.values())

    def __len__(self) -> int:
        return len(self.pages)


__all__ = ["Node", "Page", "Tree"]
