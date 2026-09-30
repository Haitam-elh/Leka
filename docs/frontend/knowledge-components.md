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

## Where they are used

- **Vue d'ensemble**: the connected sources card uses `StatusBadge`
  (`source.*`), and its times — "Il y a 4 min", "14:02" — come from the
  same helpers as the components' (`time.ts`), so no two screens can
  disagree about how long ago something was.
- **Mon environnement** (LEKA-359, [../enrichment.md § 11](../enrichment.md)):
  the screen and an entity's sheet, from what resolution and enrichment
  make — `components/environment/` draws them with `StatusBadge`,
  `KnowledgeTable` and the same time helpers. Its map is its own: mockup
  10's rows with their names and counts, which `DependencyGraph`'s free
  canvas does not draw. The Company Model's own views stay LEKA-369's
  (Knowledge Graph & Company Views, sprint 3), on the API that serves the
  company model (`/knowledge/*`, LEKA-361 — [company-model.md § 7](../company-model.md#7-the-api)).
  `DependencyGraph` and `EntityDetailPanel` are there for them.

## Adding a state

Add it to `FAMILIES` in `status.ts` with a tone and an icon, and its word in
`knowledge.status` in both dictionaries. `status-badge.test.tsx` renders
every variant, so a missing word fails there.
