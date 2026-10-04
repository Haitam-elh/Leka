# Knowledge components (LEKA-340)

How an entity of the knowledge graph, its relationships, where it came from
and how far to trust it look — the same way on every screen. The code is in
[`web/components/knowledge/`](../../web/components/knowledge/), exported from
its `index.ts`; every component, with complete, partial, empty and large data,
is on the development gallery at **`/_dev/knowledge`**.

Three rules hold for all of them:

- **Everything arrives by props.** No component fetches or calls `useQuery`.
  A page loads the data and hands it down; the component draws it.
- **Everything but the identity is optional.** A component built from the
  backend's bare `EntityRead` (id, type, name, confidence, last seen, source)
  is a correct component, with no empty boxes where data is missing.
- **Colour is never the only signal.** Every state has its own word and its
  own icon; the colour repeats them. Tooltips carry nothing the accessible
  name does not.

## The vocabulary

The entity and relationship kinds mirror the backend's
`leka/knowledge/models.py` — the company model's registry
([company-model.md § 1](../company-model.md#1-the-registry--the-kinds-of-things)):
`person`, `team`, `service`, `repository`, `project`, `issue`,
`pull_request`, `commit`, `release`, `deployment`, `incident`,
`infra_resource`, `database`, `document`, and the relationships between
them. They live in [`web/lib/knowledge.ts`](../../web/lib/knowledge.ts) as
lists — the generated API types have them as unions, which cannot be
iterated — and `api/tests/test_knowledge_mirror.py` fails the build if the
two drift.

Quality is the backend's `confidence` (0–1), shown out of 100 —
`confidenceToScore()` converts. Provenance is the source an entity came from
and when it last synced.

## Which component, when

| Component | Use it for | Key props |
|---|---|---|
| `StatusBadge` | Any state, anywhere | `variant` (`family.value`), `label?`, `dot?`, `size?`, `live?` |
| `QualityIndicator` | A score out of 100 | `score`, `label?`, `showValue?` |
| `FreshnessIndicator` | How old a piece of knowledge is | `lastUpdated`, `thresholds?`, `showLabel?` |
| `ProvenanceBadge` | Where it came from | `source` (`kind`, `name?`, `syncedAt?`), `quality?`, `staleAfterHours?` |
| `EntityCard` | One entity in a grid, a list, or a graph node (`compact`) | the entity's fields, `onClick?`, `selected?`, `compact?` |
| `DependencyList` | What an entity depends on / what depends on it | `items`, `maxVisible?`, `onSelect?` |
| `EventTimeline` | What happened, newest first | `events`, `compact?`, `maxVisible?`, `onSelect?` |
| `MetadataPanel` | Label and value pairs | `sections`, `columns?`, `copyable?` |
| `KnowledgeTable<T>` | Many entities to scan, sort and page | `columns`, `rows`, `rowKey`, `caption`, `loading?`, `empty?`, `onRowClick?` |
| `EntityDetailPanel` | Everything about one entity | `entity`, `mode` (`sidebar` / `full`), `onAskLeka?`, `onClose?`, `onSelectEntity?` |
| `DependencyGraph` | The map of entities and their links | `entities`, `relationships`, `positions?`, `onNodeClick?`, `selectedId?`, `height?`, `readOnly?` |

### StatusBadge — one table for every state

[`status.ts`](../../web/components/knowledge/status.ts) is the only place a
state gets its tone, icon and word. Seven families:

| Family | Values | Where from |
|---|---|---|
| `entity` | operational, attention, incident, unmonitored, unknown | mockup 10's legend |
| `health` | healthy, degraded, unhealthy, unknown | `HealthStatus` |
| `connector` | draft, tested, active, degraded, error, disabled | `SourceStatus` |
| `sync` | never, idle, running, failed | `SyncStatus` |
| `severity` | critical, major, minor, info | incidents |
| `priority` | high, medium, low | recommendations |
| `source` | synced, attention, error, setup, off | a source at a glance, `lib/sources.ts` |

The family prefix is what keeps `health.degraded` and `connector.degraded`
apart. `live` gives the badge `role="status"` — only for one that changes
while someone looks at it; a list of fifty live regions is fifty
interruptions.

```tsx
<StatusBadge variant="entity.incident" />
<StatusBadge variant="sync.running" live />
<StatusBadge variant="entity.operational" dot size="sm" />
```

### Quality and freshness

Quality bands: below 50 poor (red), 50–79 fair (orange), 80 and up good
(green). The indicator is a `role="meter"` whose accessible name says the
level in words.

Freshness defaults: fresh under 24 h, ageing under 7 days, stale after. Set
your own — a deployment is old after an hour, a runbook after a month:

```tsx
<FreshnessIndicator lastUpdated={entity.lastUpdated} thresholds={{ agingAfterHours: 1, staleAfterHours: 6 }} />
```

`ProvenanceBadge` turns orange with a warning icon past `staleAfterHours`
(24 h by default).

### EntityCard

Clickable through its **name**, which is stretched over the card: the
provenance and freshness badges are buttons of their own (their tooltips
open from the keyboard), and a button inside a button is invalid. Tab order
is the name, then each badge. `selected` sets `aria-current`.

### KnowledgeTable

Built on the design system's `Table`, sorted from its headers (`aria-sort`,
missing values last) and paged in the browser — TanStack Table is not a
dependency. Meant for up to a couple of hundred rows; beyond that, page on
the server (the API's lists are cursor-paged) and pass one page at a time.

```tsx
<KnowledgeTable
  caption="Services"
  columns={[
    { id: "name", header: "Nom", cell: (s) => s.name, sortValue: (s) => s.name },
    { id: "status", header: "Statut", cell: (s) => <StatusBadge variant={`entity.${s.status}`} size="sm" /> },
  ]}
  rows={services}
  rowKey={(s) => s.id}
  onRowClick={(s) => router.push(routes.entity("services", s.id))}
  empty={{ title: "Aucun service", action: <Button>Ajouter une source</Button> }}
/>
```

### EntityDetailPanel

Mockup 11 as a component. `sidebar` is one column beside a graph or list;
`full` is the entity's page, in two columns. Sections appear only when they
have data. Metric changes are written out for screen readers ("en hausse de
+68 %"); the sparklines are hand-drawn SVG and decorative.

### DependencyGraph

On React Flow (`@xyflow/react`, MIT — added for this ticket). Nodes are
compact `EntityCard`s; edges take the colour of the relationship's status
and an arrow for its direction; a relationship to an entity not shown is
dropped. Zoom, fit and reset are buttons with words. The whole graph is also
written out in a visually hidden list of entities and sentences ("Payment API
dépend de Payment DB"), for screen readers.

Without `positions`, nodes are placed one layer per kind of entity, in
mockup 10's order (people, services, repositories and deployments,
databases, infrastructure), wrapping every 10 nodes. That is a fallback,
not a layout engine: a real auto-layout (dagre or elkjs) is a follow-up, to
be added as a dependency when a page needs it.

`rowPositions(groups)` places groups the caller already has, each its own
rows, top to bottom, wrapping every 10 and centred (LEKA-369): the detailed
map hands it a walk's entities by their distance from the root, or a
view's by its rows. `layeredPositions` is `rowPositions` of the kinds'
layers. `layered(groups, links)` first splits each group by what points to
what inside it — what nothing points to on top, what it points to under it,
a loop cut where it closes — and orders each row under what it is tied to
above it: forty tables and their foreign keys read top to bottom, instead
of one row of arrows looping over each other. A link to something above it — what a walk's
things point to at its root — leaves by the top and comes in at the bottom
(`graphEdges`, given the nodes' places), rather than round the boxes.

## Where they are used

- **Vue d'ensemble**: the connected sources card uses `StatusBadge`
  (`source.*`), and its times — "Il y a 4 min", "14:02" — come from the
  same helpers as the components' (`time.ts`), so no two screens can
  disagree about how long ago something was.
- **Mon environnement** (LEKA-359, [../enrichment.md § 12](../enrichment.md)):
  the screen and an entity's sheet — `components/environment/` draws them
  with `StatusBadge`, `KnowledgeTable` and the same time helpers. It opens
  on the **Architecture** (LEKA-369, Haitam's mockup; `architecture.tsx`,
  `GET /knowledge/architecture`, [company-model.md § 16](../company-model.md)):
  `ArchitectureFigures` — how many of each kind, their states in shares —
  above every tab; `ArchitectureBoard` — **scaled to the screen it is on**
  (`useFit`: laid out wider, scaled down to the height left, 0.72 at least,
  so a 13-inch screen shows it whole; the zoom buttons there to come
  closer) — the five columns as panels, a repository's modules under it,
  each card two lines (its name; what it is and is made of) and coloured
  when something is wrong, each
  card a button (its name, kind and state its accessible name), the arrows
  an SVG measured from the cards' places once laid out, named on a pill:
  at rest a card's links to a column as one arrow (`bundles`), many
  cards' alike from their column; the chosen card's own links over them,
  alike ones to a column together, the rest faded. Beside it the chosen
  card's panel — Vue d'ensemble (why its state is deduced, in the screen's
  words: what runs it, its last deployment), Relations (each named from its
  side, a way to the other card, an inferred one with its rule and how
  sure), Événements (its sheet's); a module's parts, a machine's technical
  details. Under it the
  widgets: services by state, kinds, recent activity, the most relied on.
  Below a large screen the columns stack and the arrows go; every link is
  also said in words (`architecture-text`). The other tabs' map
  (`Cartography`) is its own: mockup 10's rows with their names and counts,
  which `DependencyGraph`'s free canvas does not draw. Each of those tabs
  is a view of the company model (`GET /knowledge/views/{view}`,
  [company-model.md § 16](../company-model.md)): `Cartography` takes the
  view's rows, boxes and lines, and `CoveragePanel` (`coverage.tsx`) says
  under it how well its kinds are known — a `role="meter"` per measure, named
  with its words, "Sans objet" where a measure does not apply — and which
  sources it comes from.
- **La cartographie détaillée** (`/environment/graph`, LEKA-369):
  `GraphExplorer` (`graph-explorer.tsx`) draws the architecture's
  **dossier** (`architecture-dossier.tsx`, after the DSI's architecture
  prompt): the architecture in layers — code, applications, data,
  technology, outside — every card and every link; the flows as sequence
  diagrams, each step numbered and named; contacts and responsibilities,
  "À confirmer" where no source names a team; the control points in
  orange; the sources read and the limits. A database's tables one choice
  away. Or a walk around one thing (`?entity=`), on `DependencyGraph` placed by
  `rowPositions`; its words are the canvas's for screen readers. The thing
  picked says what it is and can become the centre; `EntityPicker`
  (`entity-picker.tsx`) — a combobox on the knowledge search, its active
  option announced (`aria-activedescendant`), moved by a pointer that moves
  only — chooses the centre and
  where a shortest way goes. Its depth (1 to 3), direction and families of
  relationships (`RELATION_FAMILIES`, `lib/knowledge-graph.ts`) are the
  walk's.
- **An entity's context** (tab Contexte of its sheet, LEKA-370,
  `entity-context.tsx`, [../context.md § 8](../context.md)): what LEKA
  assembles around it. Its figures as one row of `Figure`s; the elements in
  order, each a row — the entity linked to its sheet, a relationship as the
  sentence it says (`t.knowledge.relationships`), why it is there, the
  logos of its sources — that opens (`aria-expanded`) on its provenance:
  sources and keys or records, stated or inferred by which rule and how
  sure, the attributes' origins grouped by source and by rule, what LEKA
  reads of it. The versions beside it, each one shown again, two compared.
  The list takes the height the screen has left (`100dvh` less the header and the report)
  so that a 13-inch screen holds the tab without the page scrolling; a role
  without `intention:create` is offered no action. Since LEKA-371: the form
  asks the period the timeline reads; each row its relevance; under the
  figures, how it was searched — each retriever and what it found, a failed
  one in orange with why in its title; a provenance opened says every way
  the element was found, its rank there and on what (the words, the steps,
  the event and when).

## Adding a state

Add it to `FAMILIES` in `status.ts` with a tone and an icon, and its word in
`knowledge.status` in both dictionaries. `status-badge.test.tsx` renders
every variant, so a missing word fails there.
