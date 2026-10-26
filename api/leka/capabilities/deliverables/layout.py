"""An application architecture deck, laid out as its template says
(agents/architecture/application-architecture/SKILL.md): title and
contents, the journey in plain words, the business rules, the application
view when asked, one slide per sub-process, the RACI, the points to
confirm, the sources — always last.

Each slide: the title bold in the principal colour (#1F3864), top left, an orange italic
subtitle under it, the same landscape page. A process slide: the whole
business layer (ArchiMate 3.0.1) on top, its sub-process framed in red, a
red line down to the front; under it, the application layer as a sequence
diagram — headers at equal intervals, lifelines behind, one chain of calls
per line, horizontal arrows only. What the sources do not hold is orange.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from leka.capabilities.deliverables.deck import (
    AppBox,
    ArchitectureDeck,
    BusinessLayer,
    Line,
    ProcessView,
)
from leka.capabilities.deliverables.scene import (
    ACTOR,
    BAND,
    BLACK,
    CREAM,
    EXTERNAL,
    FRONT,
    GREY_TEXT,
    HEIGHT,
    LIFELINE,
    MARGIN,
    NAVY,
    NEW,
    OLIVE,
    ORANGE,
    RED,
    SERVICE,
    SERVICE_LINE,
    STEEL,
    TAG,
    WHITE,
    WIDTH,
    YELLOW,
    Box,
    Cell,
    Shape,
    Slide,
    Stroke,
    Table,
    fit_size,
    row_heights,
    side_inset,
    text_height,
    text_width,
    wrap,
)

TOP = 1.05  # under the title and its subtitle
# A slide's title, at its smallest — still on one line.
TITLE_LEAST = 9.0
BOTTOM = HEIGHT - MARGIN


def header(slide: Slide, title: str, subtitle: str) -> None:
    # On one line, never over its subtitle (2026-10-23: a process slide's
    # long title wrapped onto it): smaller rather than on two lines.
    size = 20.0
    while size > TITLE_LEAST and text_width(title, size, bold=True) > WIDTH - 2 * MARGIN:
        size -= 0.5
    slide.add(
        Box(
            MARGIN,
            0.22,
            WIDTH - 2 * MARGIN,
            0.42,
            text=title,
            size=size,
            bold=True,
            color=NAVY,
            align="left",
            valign="top",
        ),
        Box(
            MARGIN,
            0.64,
            WIDTH - 2 * MARGIN,
            0.3,
            text=subtitle,
            size=11,
            italic=True,
            color=ORANGE,
            align="left",
            valign="top",
        ),
    )


def label(slide: Slide, y: float, text: str) -> None:
    slide.add(
        Box(
            MARGIN,
            y,
            5,
            0.22,
            text=text,
            size=8.5,
            bold=True,
            color=NAVY,
            align="left",
            valign="middle",
        )
    )


# ── the title slide ─────────────────────────────────────────────────────────


def title_slide(deck: ArchitectureDeck) -> Slide:
    slide = Slide()
    slide.add(
        Box(
            MARGIN,
            1.2,
            WIDTH - 2 * MARGIN,
            0.7,
            text=f"Architecture applicative - Parcours {deck.parcours}",
            size=28,
            bold=True,
            color=NAVY,
        ),
        Box(
            MARGIN,
            1.95,
            WIDTH - 2 * MARGIN,
            0.45,
            text=deck.perimetre,
            size=14,
            italic=True,
            color=ORANGE,
        ),
        Box(
            MARGIN,
            2.4,
            WIDTH - 2 * MARGIN,
            0.35,
            # The organisation as the inputs or the sources say it — no one's
            # name of LEKA's own.
            text=" | ".join(
                part
                for part in (
                    deck.organisation.strip(),
                    "Couche métier ArchiMate 3.0.1 + couche applicative en diagramme de séquence",
                )
                if part
            ),
            size=11,
            color=GREY_TEXT,
        ),
    )
    entries = [
        f"Le parcours en clair - {deck.parcours}",
        f"Règles de gestion - {deck.parcours}",
    ]
    if deck.app_view is not None:
        entries.append(f"Vue applicative - {deck.parcours}")
    entries += [
        "Les process : " + ", ".join(f"{p.letter} - {p.label}" for p in deck.processes),
        "Contacts et responsabilités (RACI)",
        "Points de contrôle / éléments à confirmer",
        "Sources consultées et limites",
    ]
    x, w = 3.2, WIDTH - 6.4
    slide.add(Box(x, 3.15, w, 0.36, text="Sommaire", size=14, bold=True, color=NAVY, align="left"))
    y = 3.6
    for n, entry in enumerate(entries, 1):
        text = f"{n} - {entry}"
        h = text_height(text, w - 0.1, 11) + 0.08
        slide.add(Box(x, y, w, h, text=text, size=11, color=BLACK, align="left", valign="top"))
        y += h
    return slide


# ── the business layer ──────────────────────────────────────────────────────


def business_layer(
    slide: Slide, layer: BusinessLayer, top: float, bottom: float, highlight: str | None = None
) -> tuple[float, float, float, float] | None:
    """The whole business layer between `top` and `bottom`; the frame of
    the grouping `highlight`, when drawn."""
    actor_x, container_x = MARGIN, MARGIN + 1.55
    right = WIDTH - MARGIN
    # The actor, named over it, its triggering event under it.
    uncertain = layer.actor.strip().endswith("?")
    head = top + 0.26
    slide.add(
        Box(
            actor_x,
            top,
            1.35,
            0.22,
            text=layer.actor,
            size=8,
            bold=True,
            color=ORANGE if uncertain else NAVY,
        ),
        Box(actor_x + 0.55, head, 0.25, 0.25, shape="ellipse", fill=ACTOR, line=ACTOR),
        Box(actor_x + 0.45, head + 0.27, 0.45, 0.3, shape="round", fill=ACTOR, line=ACTOR),
    )
    # The container, its title, its process icon.
    title = f"{layer.process_name} | {layer.channel}"
    slide.add(
        Box(
            container_x,
            top,
            right - container_x,
            bottom - top,
            shape="round",
            fill=YELLOW,
            line=OLIVE,
        ),
        Box(
            container_x + 0.3,
            top + 0.03,
            right - container_x - 0.6,
            0.22,
            text=title,
            size=fit_size(title, right - container_x - 0.7, 0.22, 8.5),
            bold=True,
        ),
        Stroke(
            right - 0.32, top + 0.13, right - 0.12, top + 0.13, color=OLIVE, width=1, arrow=True
        ),
    )
    groupings = layer.groupings
    inner_x, inner_w = container_x + 0.12, right - container_x - 0.24
    g_top, g_bottom = top + 0.3, bottom - 0.08
    gap = 0.1
    weights = [max(1, sum(1 for s in g.steps if s.branch == "main")) for g in groupings]
    usable = inner_w - gap * max(len(groupings) - 1, 0)
    # The baseline midway between the groupings' titles and their tags; a
    # step's height leaves room for a branch above and below it — the whole
    # lane when no step branches (2026-10-25: four lines in 0.3 in ran out
    # of their box).
    lane_top, lane_bottom = g_top + 0.22, g_bottom - 0.2
    baseline = (lane_top + lane_bottom) / 2
    branched = any(step.branch != "main" for g in groupings for step in g.steps)
    step_h = (
        min(0.42, (lane_bottom - lane_top - 0.12) / 3)
        if branched
        else min(0.62, lane_bottom - lane_top - 0.1)
    )
    event_y = head + 0.68
    event_h = min(0.5, max(0.36, bottom - event_y - 0.05))
    event_mid = event_y + event_h / 2
    slide.add(
        Stroke(actor_x + 0.675, head + 0.57, actor_x + 0.675, event_y, color=BLACK),
        Box(
            actor_x,
            event_y,
            1.35,
            event_h,
            shape="chevron",
            fill=CREAM,
            line=OLIVE,
            text=layer.trigger,
            size=fit_size(
                layer.trigger,
                1.35 - 2 * side_inset("chevron", 1.35, event_h, 0.04),
                event_h - 0.04,
                7,
                least=5,
            ),
        ),
    )
    # 1) the groupings' frames, side by side, all the same height.
    frames: list[tuple[float, float]] = []
    x = inner_x
    for grouping, weight in zip(groupings, weights, strict=True):
        w = usable * weight / sum(weights)
        frames.append((x, w))
        slide.add(
            Box(x, g_top, w, g_bottom - g_top, line=OLIVE, dashed=True),
            Box(
                x + 0.04,
                g_top + 0.02,
                w - 0.08,
                0.2,
                text=f"{grouping.letter} - {grouping.label}".upper(),
                size=fit_size(
                    f"{grouping.letter} - {grouping.label}".upper(), w - 0.1, 0.2, 6.5, least=4.5
                ),
                bold=True,
                align="left",
                valign="top",
            ),
            Box(
                x + w - 0.62,
                g_bottom - 0.2,
                0.58,
                0.16,
                shape="round",
                fill=TAG,
                line=TAG,
                text=f"process {grouping.letter}",
                size=6,
            ),
        )
        x += w + gap
    # 2) the baseline, behind the steps: the event to the last step; the
    # line from the event joins it.
    if frames:
        last_x, last_w = frames[-1]
        slide.add(Stroke(actor_x + 1.35, event_mid, container_x + 0.06, event_mid, color=BLACK))
        if abs(event_mid - baseline) > 0.01:
            slide.add(
                Stroke(container_x + 0.06, event_mid, container_x + 0.06, baseline, color=BLACK)
            )
        slide.add(
            Stroke(container_x + 0.06, baseline, last_x + last_w - 0.1, baseline, color=BLACK)
        )
    # 3) the steps on the baseline; alternatives above and below it, from a
    # gateway on it.
    framed = None
    for grouping, (gx, w) in zip(groupings, frames, strict=True):
        main = [s for s in grouping.steps if s.branch == "main"]
        slot = w / max(len(main), 1)
        step_w = min(1.3, slot * 0.82)
        for i, step in enumerate(main):
            sx = gx + slot * i + (slot - step_w) / 2
            slide.add(
                *_step(
                    sx, baseline - step_h / 2, step_w, step_h, step.label, step.kind, step.missing
                )
            )
        for side, offset in (("above", -1), ("below", 1)):
            branch = [s for s in grouping.steps if s.branch == side]
            for i, step in enumerate(branch[: max(len(main), 1)]):
                sx = gx + slot * i + (slot - step_w) / 2
                sy = baseline - step_h / 2 + offset * (step_h + 0.06)
                gate = sx - min(0.08, (slot - step_w) / 2)
                slide.add(
                    Stroke(gate, baseline, gate, sy + step_h / 2, color=BLACK, width=0.5),
                    Stroke(gate, sy + step_h / 2, sx, sy + step_h / 2, color=BLACK, width=0.5),
                    Box(
                        gate - 0.04,
                        baseline - 0.04,
                        0.08,
                        0.08,
                        shape="ellipse",
                        fill=WHITE,
                        line=BLACK,
                        line_width=0.5,
                    ),
                    *_step(sx, sy, step_w, step_h, step.label, step.kind, step.missing),
                )
        if highlight is not None and grouping.letter == highlight:
            framed = (gx - 0.03, g_top - 0.03, w + 0.06, g_bottom - g_top + 0.06)
    if framed is not None:
        fx, fy, fw, fh = framed
        slide.add(Box(fx, fy, fw, fh, line=RED, line_width=2))
    return framed


# The band at a business process's top where its small arrow is.
STEP_ARROW = 0.11


def _step(
    x: float, y: float, w: float, h: float, text: str, kind: str, missing: bool
) -> list[Box | Stroke]:
    """A business process (a rounded box, its small arrow top right) or a
    business event (a chevron); orange and dashed when the sources lack it."""
    color = ORANGE if missing else OLIVE
    form: Shape = "chevron" if kind == "event" else "round"
    fill = WHITE if missing else CREAM
    ink = ORANGE if missing else BLACK
    if kind == "event":
        room = w - 2 * side_inset(form, w, h, 0.04)
        size = fit_size(text, room, h - 0.06, 7, least=4.5)
        return [
            Box(
                x,
                y,
                w,
                h,
                shape=form,
                fill=fill,
                line=color,
                dashed=missing,
                text=text,
                size=size,
                color=ink,
            )
        ]
    # Its words under its arrow, never across it (2026-10-25: four lines in
    # a narrow box ran under « ⇒ »): the shape, its arrow, then its text in
    # the room left below.
    top = y + STEP_ARROW
    room_w, room_h = w - 0.1, h - STEP_ARROW - 0.03
    return [
        Box(x, y, w, h, shape=form, fill=fill, line=color, dashed=missing),
        Stroke(x + w - 0.17, y + 0.06, x + w - 0.05, y + 0.06, color=color, width=0.5, arrow=True),
        Box(
            x + 0.05,
            top,
            room_w,
            room_h,
            text=text,
            size=fit_size(text, room_w - 0.04, room_h - 0.02, 7, least=4.5),
            color=ink,
            inset=0.01,
        ),
    ]


# ── the journey in plain words ──────────────────────────────────────────────


def _span(deck: ArchitectureDeck) -> str:
    letters = [g.letter for g in deck.business.groupings] or ["A"]
    return f"{letters[0]} -> {letters[-1]}"


def overview_slide(deck: ArchitectureDeck) -> Slide:
    slide = Slide()
    header(
        slide,
        f"Le parcours en clair - {deck.parcours}",
        "Couche métier seule (ArchiMate 3.0.1) - explication pédagogique de bout en bout",
    )
    label(slide, TOP - 0.05, "COUCHE MÉTIER - ArchiMate 3.0.1")
    business_layer(slide, deck.business, TOP + 0.22, TOP + 2.45)
    o = deck.overview
    paragraphs = [
        ("1. Objectif du parcours", o.objectif),
        ("2. Déclencheur et acteurs", o.declencheur_acteurs),
        (f"3. Déroulé étape par étape ({_span(deck)})", o.deroule),
        ("4. Règles de gestion clés et cas particuliers", o.regles_cles),
        ("5. Données et flux principaux", o.donnees_flux),
        ("6. Points d'attention / manques (éléments ORANGE)", o.points_attention),
    ]
    y0 = TOP + 2.6
    avail = BOTTOM - y0
    full = WIDTH - 2 * MARGIN
    half = (full - 0.3) / 2

    def height(width: float, size: float, chunk: Sequence[tuple[str, str]]) -> float:
        return sum(0.2 + text_height(text or "-", width, size) + 0.06 for _, text in chunk)

    # On the whole width, as the template says; in two columns only when the
    # text would otherwise fall under 7 pt.
    size, columns = 9.0, [paragraphs]
    while size > 7 and height(full, size, paragraphs) > avail:
        size -= 0.5
    if height(full, size, paragraphs) > avail:
        size, columns = 9.0, [paragraphs[:3], paragraphs[3:]]
        while size > 5.5 and max(height(half, size, c) for c in columns) > avail:
            size -= 0.5
    col_w = full if len(columns) == 1 else half
    for column, chunk in enumerate(columns):
        x = MARGIN + column * (col_w + 0.3)
        y = y0
        for title, text in chunk:
            body = text or "-"
            h = text_height(body, col_w, size)
            slide.add(
                Box(
                    x,
                    y,
                    col_w,
                    0.2,
                    text=title,
                    size=size + 0.5,
                    bold=True,
                    color=NAVY,
                    align="left",
                    valign="top",
                ),
                Box(
                    x,
                    y + 0.2,
                    col_w,
                    h + 0.04,
                    text=body,
                    size=size,
                    align="left",
                    valign="top",
                    color=ORANGE if title.startswith("6") else BLACK,
                ),
            )
            y += 0.2 + h + 0.06
    return slide


# ── tables over as many slides as they need ─────────────────────────────────


def table_slides(
    title: str,
    subtitle: str,
    head: Sequence[str],
    widths: Sequence[float],
    rows: Sequence[Sequence[Cell]],
    *,
    size: float = 8,
    top: float = TOP,
    note: str = "",
    fill_height: bool = False,
) -> list[Slide]:
    """A native table filling each slide before the next; the header
    repeated; the note under the table, on the last. `fill_height`: the
    rows grow to take the slide's whole height (the RACI's rule), each at
    most doubled."""
    total = sum(widths)
    scale = (WIDTH - 2 * MARGIN) / total
    widths = tuple(w * scale for w in widths)
    margin = 0.03
    head_h = row_heights([list(head)], widths, size, margin)[0]
    heights = row_heights([[c.text for c in r] for r in rows], widths, size, margin)
    note_h = text_height(note, WIDTH - 2 * MARGIN, size) + 0.1 if note else 0
    slides: list[Slide] = []
    start = 0
    while True:
        slide = Slide()
        header(slide, title if not slides else f"{title} (suite)", subtitle)
        room = BOTTOM - top - head_h
        end = start
        used = 0.0
        while end < len(rows) and used + heights[end] <= room:
            used += heights[end]
            end += 1
        if end == start and start < len(rows):
            end = start + 1  # a row taller than a slide: on its own
            used = heights[start]
        last = end >= len(rows)
        if last and note and used + note_h > room and end > start + 1:
            end -= 1
            used -= heights[end]
            last = False
        shown = list(heights[start:end])
        if fill_height and shown:
            spare = room - used - (note_h + 0.05 if last and note else 0)
            grown = [min(h * 2, h + spare / len(shown)) for h in shown]
            used += sum(grown) - sum(shown)
            shown = grown
        slide.add(
            Table(
                MARGIN,
                top,
                widths,
                tuple(head),
                tuple(tuple(r) for r in rows[start:end]),
                (head_h, *shown),
                size=size,
                margin=margin,
            )
        )
        if last and note:
            slide.add(
                Box(
                    MARGIN,
                    top + head_h + used + 0.05,
                    WIDTH - 2 * MARGIN,
                    note_h,
                    text=note,
                    size=size,
                    align="left",
                    valign="top",
                    color=GREY_TEXT,
                )
            )
        slides.append(slide)
        start = end
        if last:
            return slides


def _status(text: str) -> Cell:
    pending = text.strip().lower().startswith(("à confirmer", "a confirmer", "non document"))
    return Cell(text, color=ORANGE if pending else BLACK, bold=pending)


def _domain(perimetre: str) -> str:
    """« Périmètre Digital - Espace Client » -> « Digital »."""
    text = perimetre.strip()
    if text.lower().startswith("périmètre "):
        text = text[len("périmètre ") :]
    return text.split(" - ")[0].strip() or text


def rules_slides(deck: ArchitectureDeck) -> list[Slide]:
    rows = [
        [
            Cell(str(n)),
            Cell(r.etape),
            Cell(r.regle),
            Cell(r.exception),
            Cell(r.source),
            _status(r.statut),
        ]
        for n, r in enumerate(deck.rules, 1)
    ] or [
        [
            Cell("-"),
            Cell("-"),
            Cell("Aucune règle trouvée dans les sources"),
            Cell(""),
            Cell(""),
            _status("À confirmer"),
        ]
    ]
    return table_slides(
        f"Règles de gestion - {deck.parcours}",
        "Couche métier seule - les règles déduites et non documentées sont en ORANGE",
        [
            "N",
            "Étape concernée",
            "Règle de gestion",
            "Exception / cas particulier",
            "Source",
            "Statut",
        ],
        [0.4, 1.8, 4.0, 2.8, 1.8, 1.0],
        rows,
        size=8.5,
    )


def raci_slides(deck: ArchitectureDeck) -> list[Slide]:
    rows = [
        [
            Cell(c.application),
            Cell(c.domaine),
            Cell(c.int_ext),
            Cell(c.role),
            Cell(c.raci),
            Cell(c.contact, color=ORANGE if c.contact.lower().startswith("à confirmer") else BLACK),
            Cell(c.coordonnees),
            Cell(c.source),
            _status(c.statut),
        ]
        for c in deck.raci
    ] or [
        [
            Cell("-"),
            Cell(""),
            Cell(""),
            Cell(""),
            Cell(""),
            Cell("À confirmer", color=ORANGE),
            Cell(""),
            Cell(""),
            _status("À confirmer"),
        ]
    ]
    return table_slides(
        f"Contacts et responsabilités (RACI) - parcours {deck.parcours} / périmètre "
        f"{_domain(deck.perimetre)}",
        "Ne jamais inventer un nom : 'À confirmer' uniquement quand la requête annuaire est "
        "restée sans résultat",
        [
            "Application / Composant",
            "Domaine",
            "Int. / Ext.",
            "Rôle / Fonction",
            "RACI",
            "Contact (nom)",
            "Coordonnées",
            "Source",
            "Statut",
        ],
        [1.7, 1.0, 0.6, 1.6, 0.45, 1.5, 1.7, 1.6, 0.9],
        rows,
        size=8,
        note=("Contacts à confirmer : " + deck.raci_notes) if deck.raci_notes else "",
        fill_height=True,
    )


def controls_slides(deck: ArchitectureDeck) -> list[Slide]:
    rows = [
        [Cell(c.manque, color=ORANGE), Cell(c.localisation), Cell(c.question)]
        for c in deck.controls
    ] or [[Cell("Aucun élément à confirmer"), Cell(""), Cell("")]]
    return table_slides(
        "Points de contrôle / éléments à confirmer (éléments ORANGE des schémas)",
        "Confrontation métier <-> applicatif <-> infrastructure",
        ["Manque / point de contrôle (ORANGE)", "Localisation", "Question à trancher"],
        [4.4, 2.0, 5.6],
        rows,
        size=8.5,
    )


def sources_slides(deck: ArchitectureDeck) -> list[Slide]:
    rows = [[Cell(s.source), Cell(s.elements), _status(s.statut)] for s in deck.sources] or [
        [Cell("Aucune source consultée"), Cell(""), _status("Non documenté")]
    ]
    return table_slides(
        "Sources consultées et limites",
        "Traçabilité obligatoire - SharePoint / Confluence",
        ["Source", "Éléments extraits", "Statut"],
        [4.0, 6.4, 1.6],
        rows,
        size=8.5,
    )


# ── a process slide ─────────────────────────────────────────────────────────

LINE_H = 0.34
BOX_H = 0.26
APP_TOP = TOP + 2.25  # the application layer, under the business layer
HEAD_Y = APP_TOP + 0.08
HEAD_H = 0.36
BANDS_TOP = HEAD_Y + HEAD_H + 0.25
BAND_HEAD = 0.24  # a band's title banner
BAND_GAP = 0.08

# A process slide's bands: each band's title and the lines it shows there.
Page = list[tuple[str, list[Line]]]


def process_slides(deck: ArchitectureDeck, process: ProcessView) -> list[Slide]:
    """The process's slide — split in (1/2), (2/2)… when its lines do not
    fit, the business layer repeated; a band is cut only when it cannot
    fit a slide of its own."""
    room = BOTTOM - BANDS_TOP
    pages: list[Page] = [[]]
    used = 0.0
    for band in (b for b in process.bands if b.lines):
        lines = list(band.lines)
        whole = BAND_HEAD + len(lines) * LINE_H + BAND_GAP
        if pages[-1] and used + whole > room and whole <= room:
            pages.append([])
            used = 0.0
        while lines:
            fits = int((room - used - BAND_HEAD - BAND_GAP) // LINE_H)
            if fits <= 0:
                pages.append([])
                used = 0.0
                continue
            pages[-1].append((band.title, lines[:fits]))
            used += BAND_HEAD + len(lines[:fits]) * LINE_H + BAND_GAP
            lines = lines[fits:]
    total = len(pages)
    return [
        _process_slide(deck, process, page, (i + 1, total) if total > 1 else None)
        for i, page in enumerate(pages)
    ]


def _process_slide(
    deck: ArchitectureDeck, process: ProcessView, bands: Page, part: tuple[int, int] | None
) -> Slide:
    slide = Slide()
    suffix = f" ({part[0]}/{part[1]})" if part else ""
    header(
        slide,
        f"Parcours {deck.parcours} - Vue globale - process {process.letter} : {process.letter} - "
        f"{process.label.upper()}{suffix}",
        "Couche métier complète (ArchiMate 3.0.1) + couche applicative du seul sous-processus "
        "développé (encadré en rouge)",
    )
    label(slide, TOP - 0.05, "COUCHE MÉTIER - ArchiMate 3.0.1")
    framed = business_layer(slide, deck.business, TOP + 0.2, TOP + 2.0, highlight=process.letter)
    # The layer's label left of its headers, clear of the red line.
    slide.add(
        Box(
            MARGIN,
            HEAD_Y,
            1.5,
            HEAD_H,
            text="COUCHE APPLICATIVE -\nDiagramme de séquence",
            size=8,
            bold=True,
            color=NAVY,
            align="left",
            valign="middle",
            inset=0,
        )
    )
    left, right = MARGIN + 1.55, WIDTH - MARGIN
    columns = process.columns
    n = 1 + len(columns)
    pitch = (right - left) / n
    centers = [left + pitch * (i + 0.5) for i in range(n)]
    sub_y = HEAD_Y + HEAD_H + 0.01
    life_top = sub_y + 0.2
    band_boxes: list[tuple[str, list[Line], float, float]] = []
    y = BANDS_TOP
    for title, lines in bands:
        h = BAND_HEAD + len(lines) * LINE_H
        band_boxes.append((title, lines, y, h))
        y += h + BAND_GAP
    bottom = max(y - BAND_GAP, BANDS_TOP + 0.4)
    # 1) the bands, grey, dashed.
    band_left = centers[0] + pitch * 0.18 + 0.08
    for _, _, by, bh in band_boxes:
        slide.add(Box(band_left, by, right - band_left, bh, fill=BAND, line="A6A6A6", dashed=True))
    # 2) the lifelines, behind.
    for cx in centers[1:]:
        slide.add(Stroke(cx, life_top, cx, bottom, color=LIFELINE, width=0.75))
    # 3) the bands' titles, opaque.
    banners: list[tuple[float, float, float, float]] = []
    for i, (title, _, by, _) in enumerate(band_boxes, 1):
        text = f"{i} - {title.upper()}"
        bw = min(text_width(text, 6.5, bold=True) + 0.16, right - band_left - 0.1)
        banners.append((band_left + 0.04, by + 0.03, bw, 0.18))
        slide.add(
            Box(
                band_left + 0.04,
                by + 0.03,
                bw,
                0.18,
                fill=WHITE,
                line="7F7F7F",
                text=text,
                size=fit_size(text, bw - 0.08, 0.18, 6.5, least=5, bold=True),
                bold=True,
                align="left",
            )
        )
    # 4) the front block, the headers.
    front_w = pitch * 0.36
    slide.add(
        Box(
            centers[0] - pitch * 0.35,
            HEAD_Y,
            pitch * 0.7,
            HEAD_H,
            fill=STEEL,
            line=STEEL,
            text=process.front,
            size=fit_size(process.front, pitch * 0.66, HEAD_H, 7.5, bold=True),
            bold=True,
            color=WHITE,
        ),
        Box(
            centers[0] - pitch * 0.45,
            sub_y,
            pitch * 0.9,
            0.18,
            text=process.channel_label,
            size=6,
            italic=True,
            color=GREY_TEXT,
        ),
        Box(
            centers[0] - front_w / 2,
            BANDS_TOP,
            front_w,
            bottom - BANDS_TOP,
            fill=FRONT,
            line=FRONT,
            text=process.front_label,
            size=fit_size(process.front_label, front_w - 0.08, 0.6, 7, bold=True),
            bold=True,
        ),
    )
    for column, cx in zip(columns, centers[1:], strict=False):
        fill = ORANGE if column.missing else STEEL
        name = column.name + (" ?" if column.missing and not column.name.endswith("?") else "")
        slide.add(
            Box(
                cx - pitch * 0.45,
                HEAD_Y,
                pitch * 0.9,
                HEAD_H,
                fill=fill,
                line=fill,
                text=name,
                size=fit_size(name, pitch * 0.72, HEAD_H, 7.5, bold=True),
                bold=True,
                color=WHITE,
            ),
            *_component_icon(cx + pitch * 0.45 - 0.17, HEAD_Y + 0.04),
            Box(
                cx - pitch * 0.48,
                sub_y,
                pitch * 0.96,
                0.18,
                text=column.subtitle or ("brique à confirmer" if column.missing else ""),
                size=6,
                italic=True,
                color=ORANGE if column.missing else GREY_TEXT,
            ),
        )
    # 5) and 6) the arrows and the bus, then the service boxes in front.
    index = {c.name.strip().lower(): i for i, c in enumerate(columns)}
    box_w = pitch * 0.72
    first_left = centers[1] - box_w / 2 if len(centers) > 1 else right
    bus_x = first_left - 0.25
    branches: list[float] = []
    boxes: list[Box] = []
    arrows: list[Stroke] = []
    for _, lines, by, _ in band_boxes:
        for li, line in enumerate(lines):
            cy = by + BAND_HEAD + li * LINE_H + LINE_H / 2
            placed: list[tuple[float, bool]] = []
            for call in line.calls:
                ci = index.get(call.column.strip().lower())
                if ci is None:
                    continue
                cx = centers[ci + 1]
                text = call.label + (
                    " ? (à confirmer)" if call.missing and "?" not in call.label else ""
                )
                fill, color = (ORANGE, WHITE) if call.missing else (SERVICE, BLACK)
                boxes.append(
                    Box(
                        cx - box_w / 2,
                        cy - BOX_H / 2,
                        box_w,
                        BOX_H,
                        shape="round",
                        fill=fill,
                        line=ORANGE if call.missing else SERVICE_LINE,
                        text=text,
                        size=fit_size(text, box_w - 0.1, BOX_H - 0.04, 6.5, least=4.5),
                        color=color,
                    )
                )
                placed.append((cx, call.missing))
            if not placed:
                continue
            branches.append(cy)
            arrows.append(
                Stroke(
                    bus_x,
                    cy,
                    placed[0][0] - box_w / 2,
                    cy,
                    color=ORANGE if placed[0][1] else SERVICE_LINE,
                    dashed=placed[0][1],
                    arrow=True,
                )
            )
            for (ax, _), (bx, missing) in pairwise(placed):
                start, end = (
                    (ax + box_w / 2, bx - box_w / 2)
                    if bx > ax
                    else (ax - box_w / 2, bx + box_w / 2)
                )
                arrows.append(
                    Stroke(
                        start,
                        cy,
                        end,
                        cy,
                        color=ORANGE if missing else SERVICE_LINE,
                        dashed=missing,
                        arrow=True,
                    )
                )
    if branches:
        # From the middle of the front's right edge to the bus; the bus from
        # the first branch to the last, no further — and never across a
        # band's title.
        front_right = centers[0] + front_w / 2
        mid = min(max((BANDS_TOP + bottom) / 2, min(branches)), max(branches))
        # Its middle on a band's title: at the branch nearest it instead — a
        # title is never struck through (§5.6; 2026-10-25, « 2 - PAIEMENT »).
        if any(
            by0 <= mid <= by0 + bh0 and bx0 < bus_x and bx0 + bw0 > front_right
            for bx0, by0, bw0, bh0 in banners
        ):
            mid = min(branches, key=lambda y: abs(y - mid))
        slide.add(Stroke(front_right, mid, bus_x, mid, color=SERVICE_LINE))
        top_y = min(branches)
        for bx0, by0, bw0, bh0 in banners:
            if bx0 <= bus_x <= bx0 + bw0 and top_y < by0 < max(branches):
                slide.add(Stroke(bus_x, top_y, bus_x, by0, color=SERVICE_LINE))
                top_y = by0 + bh0
        slide.add(Stroke(bus_x, top_y, bus_x, max(branches), color=SERVICE_LINE))
    slide.add(*arrows, *boxes)
    # The red line: from the framed grouping down, left, then down onto the
    # front's header.
    if framed is not None:
        fx, fy, fw, fh = framed
        mx, below = fx + fw / 2, fy + fh + 0.08
        fx0 = centers[0]
        slide.add(
            Stroke(mx, fy + fh, mx, below, color=RED, width=1.5),
            Stroke(fx0, below, mx, below, color=RED, width=1.5),
            Stroke(fx0, below, fx0, HEAD_Y, color=RED, width=1.5, arrow=True),
        )
    return slide


def _component_icon(x: float, y: float) -> list[Box]:
    """ArchiMate's application component, small, top right of a header."""
    return [
        Box(x + 0.03, y, 0.1, 0.12, line=WHITE, line_width=0.5),
        Box(x, y + 0.02, 0.06, 0.03, fill=WHITE, line=WHITE, line_width=0.25),
        Box(x, y + 0.07, 0.06, 0.03, fill=WHITE, line=WHITE, line_width=0.25),
    ]


# ── the application view ────────────────────────────────────────────────────


_APP_STYLE: dict[str, tuple[str, str, str, bool, Shape]] = {
    # fill, line, text, dashed, shape
    "perimetre": (STEEL, STEEL, WHITE, False, "rect"),
    "connexe": (SERVICE, SERVICE_LINE, BLACK, False, "rect"),
    "externe": (EXTERNAL, "7F7F7F", BLACK, True, "rect"),
    "middleware": (NAVY, NAVY, WHITE, False, "hexagon"),
    "a_confirmer": (WHITE, ORANGE, ORANGE, True, "rect"),
}

_FLOW_COLOR = {"Existant": SERVICE_LINE, "Nouveau": NEW, "À confirmer": ORANGE}


def app_view_slides(deck: ArchitectureDeck) -> list[Slide]:
    """The application view: sources and fronts on the left, the core in
    the middle, targets on the right; orthogonal flows, numbered, each with
    its label; the legend bottom left, the flows' catalogue beside it or on
    a (2/2) slide."""
    view = deck.app_view
    if view is None:
        return []
    linked = {f.source for f in view.flows} | {f.target for f in view.flows}
    counted = {
        a.name
        for a in view.apps
        if a.kind != "middleware" and a.name in linked and a.name.strip().lower() != "client"
    }
    slide = Slide()
    header(
        slide,
        f"Vue applicative - {deck.parcours}",
        f"Interactions entre {len(counted)} applications et briques du SI - flux, interfaces "
        "et données échangées",
    )
    sources = {f.source for f in view.flows}
    targets = {f.target for f in view.flows}
    lanes: dict[str, list[AppBox]] = {"left": [], "center": [], "right": []}
    for app in view.apps:
        if app.name in sources and app.name not in targets:
            lanes["left"].append(app)
        elif app.name in targets and app.name not in sources:
            lanes["right"].append(app)
        else:
            lanes["center"].append(app)
    area_top, area_bottom = TOP + 0.15, BOTTOM - 1.95
    box_w = 2.3
    xs = {
        "left": MARGIN + 0.1,
        "center": (WIDTH - box_w) / 2,
        "right": WIDTH - MARGIN - 0.1 - box_w,
    }
    where: dict[str, tuple[float, float, float, float]] = {}
    for lane, apps in lanes.items():
        if not apps:
            continue
        slot = (area_bottom - area_top) / len(apps)
        for i, app in enumerate(apps):
            h = max(0.45, min(0.95, slot - 0.25))
            y = area_top + slot * i + (slot - h) / 2
            where[app.name] = (xs[lane], y, box_w, h)
    # Each side of a box shares its height between the flows that use it.
    ports: dict[tuple[str, str], list[int]] = {}
    routes = []
    for i, flow in enumerate(view.flows):
        a, b = where.get(flow.source), where.get(flow.target)
        if a is None or b is None or flow.source == flow.target:
            continue
        if b[0] > a[0] + 0.01:
            out, into = "right", "left"
        elif b[0] < a[0] - 0.01:
            out, into = "left", "right"
        else:
            out, into = "left", "left"  # the same lane: round its left side
        ports.setdefault((flow.source, out), []).append(i)
        ports.setdefault((flow.target, into), []).append(i)
        routes.append((i, flow, a, b, out, into))

    def port(name: str, side: str, i: int) -> tuple[float, float]:
        x, y, w, h = where[name]
        users = ports[(name, side)]
        k = users.index(i)
        return (x + w if side == "right" else x, y + h * (k + 1) / (len(users) + 1))

    # Flows first, behind the boxes.
    gaps: dict[tuple[float, float], int] = {}
    for i, flow, a, _b, out, into in routes:
        x1, y1 = port(flow.source, out, i)
        x2, y2 = port(flow.target, into, i)
        color = _FLOW_COLOR[flow.status]
        dashed = flow.mode == "async" or flow.status == "À confirmer"
        if out == into:  # the same lane
            k = gaps[(a[0], -1)] = gaps.get((a[0], -1), 0) + 1
            elbow = x1 - 0.12 - 0.1 * k
            legs = [(x1, y1, elbow, y1), (elbow, y1, elbow, y2), (elbow, y2, x2, y2)]
            label_x, label_w, label_y = elbow - 1.2, 1.15, (y1 + y2) / 2 - 0.08
        else:
            lo, hi = sorted((x1, x2))
            k = gaps[(lo, hi)] = gaps.get((lo, hi), 0) + 1
            elbow = lo + (hi - lo) * min(0.25 + 0.12 * (k - 1), 0.75)
            legs = [(x1, y1, elbow, y1), (elbow, y1, elbow, y2), (elbow, y2, x2, y2)]
            # The label along the longer horizontal leg.
            if abs(x2 - elbow) >= abs(elbow - x1):
                label_x, label_w, label_y = min(elbow, x2) + 0.25, abs(x2 - elbow) - 0.3, y2
            else:
                label_x, label_w, label_y = min(x1, elbow) + 0.05, abs(elbow - x1) - 0.3, y1
            label_y -= 0.17
        for n, (sx, sy, ex, ey) in enumerate(legs):
            if abs(sx - ex) < 0.005 and abs(sy - ey) < 0.005:
                continue
            slide.add(Stroke(sx, sy, ex, ey, color=color, dashed=dashed, arrow=n == len(legs) - 1))
        text = " - ".join(t for t in (flow.interface, flow.data) if t)
        if flow.status == "À confirmer" and not text.endswith("?"):
            text += " ?"
        if text and label_w > 0.4:
            slide.add(
                Box(
                    label_x,
                    label_y,
                    label_w,
                    0.15,
                    text=text,
                    size=fit_size(text, label_w, 0.15, 7, least=5),
                    color="404040",
                    align="left",
                    valign="bottom",
                    inset=0.01,
                )
            )
        slide.add(
            Box(
                elbow - 0.11,
                min(y1, y2) + abs(y2 - y1) / 2 - 0.11,
                0.22,
                0.22,
                shape="ellipse",
                fill=WHITE,
                line=color,
                text=flow.n,
                size=6.5,
                bold=True,
                inset=0,
            )
        )
    # The boxes, in front; their data stores inside.
    for app in view.apps:
        if app.name not in where:
            continue
        x, y, w, h = where[app.name]
        fill, line, color, dashed, shape = _APP_STYLE[app.kind]
        name = app.name + (" ?" if app.kind == "a_confirmer" and not app.name.endswith("?") else "")
        stores = app.stores[:3]
        text_w = w - 0.2 - (0.75 if stores else 0)
        text = name + (f"\n{app.role}" if app.role else "")
        slide.add(
            Box(
                x,
                y,
                w,
                h,
                shape=shape,
                fill=fill,
                line=line,
                dashed=dashed,
                text=text,
                size=fit_size(text, text_w, h - 0.06, 8.5, least=5.5),
                bold=True,
                color=color,
            )
        )
        if stores:
            ch = min(0.3, (h - 0.08) / len(stores) - 0.03)
            for k, store in enumerate(stores):
                slide.add(
                    Box(
                        x + w - 0.78,
                        y + 0.04 + k * (ch + 0.03),
                        0.72,
                        ch,
                        shape="can",
                        fill=WHITE,
                        line=SERVICE_LINE,
                        text=store,
                        size=fit_size(store, 0.66, ch, 7, least=4.5),
                    )
                )
    # The legend, bottom left.
    legend = [
        ("Flux synchrone existant", SERVICE_LINE, False),
        ("Flux asynchrone existant", SERVICE_LINE, True),
        ("Nouveau flux synchrone", NEW, False),
        ("Nouveau flux asynchrone", NEW, True),
        ("Élément à confirmer", ORANGE, True),
    ]
    ly = BOTTOM - 1.75
    slide.add(
        Box(MARGIN, ly, 2.6, 1.75, fill=WHITE, line="7F7F7F"),
        Box(
            MARGIN + 0.1,
            ly + 0.03,
            2.4,
            0.2,
            text="Légende",
            size=7.5,
            bold=True,
            color=NAVY,
            align="left",
        ),
    )
    for i, (text, color, dashed) in enumerate(legend):
        y = ly + 0.3 + i * 0.28
        slide.add(
            Stroke(
                MARGIN + 0.1,
                y + 0.08,
                MARGIN + 0.6,
                y + 0.08,
                color=color,
                dashed=dashed,
                arrow=True,
            ),
            Box(MARGIN + 0.7, y, 1.85, 0.18, text=text, size=7, align="left"),
        )
    if not view.flows:
        return [slide]
    rows = [
        [
            Cell(f.n),
            Cell(f"{f.source} -> {f.target}"),
            Cell(f.interface),
            Cell(f.mode),
            Cell(f.data, color=ORANGE if f.status == "À confirmer" else BLACK),
            Cell(f.status, color=ORANGE if f.status == "À confirmer" else BLACK),
        ]
        for f in view.flows
    ]
    head = [
        "N°",
        "Source -> Cible",
        "Type d'interface",
        "Mode (sync / async)",
        "Données échangées",
        "Statut",
    ]
    widths = [0.35, 2.6, 1.6, 0.85, 3.0, 0.95]
    heights = row_heights([head] + [[c.text for c in r] for r in rows], widths, 7, 0.03)
    if sum(heights) <= 1.75:
        slide.add(
            Table(
                MARGIN + 2.8,
                ly,
                tuple(widths),
                tuple(head),
                tuple(tuple(r) for r in rows),
                tuple(heights),
                size=7,
            )
        )
        return [slide]
    return [
        slide,
        *table_slides(
            f"Vue applicative - {deck.parcours} (2/2) - Catalogue des flux",
            "Traçabilité des données échangées",
            head,
            widths,
            rows,
            size=7.5,
        ),
    ]


# ── the deck ────────────────────────────────────────────────────────────────


def deck_slides(deck: ArchitectureDeck) -> list[Slide]:
    """Every slide, in the template's order: title, journey, rules, the
    application view when there is one, the processes, the RACI, the
    points to confirm, the sources — last."""
    slides = [title_slide(deck), overview_slide(deck), *rules_slides(deck), *app_view_slides(deck)]
    for process in deck.processes:
        slides.extend(process_slides(deck, process))
    slides += [*raci_slides(deck), *controls_slides(deck), *sources_slides(deck)]
    return slides


__all__ = ["deck_slides", "wrap"]
