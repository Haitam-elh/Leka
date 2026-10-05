# The context API — for LEKA's services and screens

How to ask LEKA for the context of a request, read it back, inspect what it
holds down to the records it was read from, follow it as it changes, and
what each of those asks of the caller. What the context engine does is
[context.md](context.md); how the API behaves in general — errors, paging,
the request id — is [api.md](api.md). This page is what a client of
`/api/v1/context` needs, and what LEKA-376 made stable.

Two kinds of client:

- **LEKA's own services** — intentions, capabilities, the analysis engine —
  run in the API's process and call `ContextService` in Python (§ 8). They
  read the same contract the HTTP API serves.
- **Product surfaces** — the web app today — call the HTTP API with the
  person's session.

---

## 1. Who may ask, and for what

A request carries the person's **session** (the cookie set at sign-in) and,
when it changes something, the **CSRF token** (`X-CSRF-Token`) —
[security.md](security.md). The **workspace is the session's**, never the
URL's or the body's: another workspace's context answers **404**, on every
route, exactly as if it did not exist.

| Route | Asks | |
|---|---|---|
| `POST /context`, `POST /context/intents` | `intention:create` | assemble a context — from roots and words, or from an intention |
| `POST /context/intents/plan` | `intention:read` | what an intention asks for — nothing kept |
| `GET /context`, `GET /context/{id}`, `/versions`, `/assembled`, `/diff`, `/checks`, `/quality`, `/elements/{ref}` | `intention:read` | read, inspect, history |
| `GET /context/{id}/elements/{ref}/evidence` | `intention:read` **and** `source:read` | the source records behind an element: what they say is the sources' |
| `GET /context/{id}/events` | `intention:read` | what happens to it, streamed (§ 5) |
| `GET /context/contract`, `GET /context/feedback` | `intention:read` | the contract (§ 3); what people said, counted |
| `POST /context/{id}/refresh`, `/expand`, `/compress`, `/intent`, `/feedback` | `intention:create` | make it again, widen, narrow, ask again, say something of it |
| `PATCH /context/{id}`, `POST /context/{id}/archive` | `intention:create`, and its **maker** — or `context:manage` (admin and above) | change how it follows the model, archive it: what everyone reads of it is not one member's to end |

The matrix of roles is [permissions.md](permissions.md). A **suspended
workspace** reads its contexts and makes none (403 on every write). Nobody
signed in gets **401** everywhere. `tests/test_context_api_security.py`
checks every one of these, route by route, and fails when a context route
is added without saying what it asks.

## 2. Errors

The shape is [api.md](api.md)'s. What the context routes answer:

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_filter` | `?version=` and `?at=` together |
| 401 | `not_authenticated` | no session |
| 403 | `permission_denied` | a role without the permission; another member's context archived or unfollowed; a suspended workspace writing |
| 403 | `csrf_failed` | a write without its CSRF token |
| 404 | `not_found` | no such context — or another workspace's — version, or element in that version; a root not the workspace's |
| 406 | `contract_unsupported` | `Leka-Context-Contract` asks for a contract this API does not serve (§ 3) |
| 409 | `conflict` | an archived context made again; asking again what was not an intention |
| 422 | `validation_failed` | a body that says nothing — no roots and no words, a widening that narrows, feedback naming nothing |

## 3. The contract, and its versions

What a context **is** — `AssembledContext`, one version whole — is a
contract services build on: **contract version 1**.

- **Every response says it**: `Leka-Context-Contract: 1`.
- **A client may ask for one**: send `Leka-Context-Contract: 1`. One this
  API does not serve is refused, **406** `contract_unsupported`, before
  anything is read or made.
- **It is published**: `GET /api/v1/context/contract` — the version, the
  versions a client may ask for, what each part is judged by (`ranking`,
  `quality`, `intent`, `strategy.<name>`), the **JSON Schema** of
  `AssembledContext`, and what each ticket added. The OpenAPI schema is not
  served in production (ADR 011); this is, to whoever may read contexts.

**The rules.** Inside a contract version, fields are only **added** —
LEKA-371 `retrieval`, `relevance`, `reason.retrievers`; LEKA-372 `ranking`,
`conflicts`; LEKA-373 `intent`; LEKA-374 `trigger`, `reason`, `changes`,
`change_count`, `delta`; LEKA-375 `quality`. A field that changes meaning or
goes raises `CONTRACT_VERSION`; each version of a context keeps the one it
was made under, and reads back as it was made. Write clients that ignore a
field they do not know. A part judged differently — the ranking, the
quality — raises its own version in `versions`, kept with every version of
a context, without changing the contract's shape.

## 4. Flows, end to end

**Assemble for an intention, read it, inspect it.**

```http
POST /api/v1/context/intents
{"text": "Pourquoi l'API de paiement est-elle plus lente depuis hier ?"}
→ 201 AssembledContext: context_id, version 1, elements (each with its
  provenance, why it is there, how it was ranked), intent, quality

GET /api/v1/context/{id}/elements/{ref_id}
→ ElementInspection: the element; what the version's quality says of it —
  gaps, factors, conflicts naming it; its history across versions — held,
  rank, what changed; what people said of it

GET /api/v1/context/{id}/elements/{ref_id}/evidence
→ ElementEvidence: the records it was read from — source, id there, title,
  link, state, dates, the start of their text, gone or not
```

An entity's evidence is every record whose key, from its source, entity
resolution made it; a relationship's, the records that stated it. A
record the source no longer shows is said `gone` and listed last.

**Query.** `GET /context` pages the contexts, the latest changed first,
and filters them:

| Filter | |
|---|---|
| `status`, `subject_type`, `subject_id` | where it stands; what it is the context of |
| `stale` | behind the model, or up to date ([context.md](context.md) § 14) |
| `holds=<entity id>` | its latest version holds this entity — which contexts a change to it touches |
| `q=` | these words in its title or purpose, taken literally |
| `level=high\|medium\|low` | its latest version judged so ([context.md](context.md) § 15) |
| `mine=true` | made by who asks |

**History.** `GET /context/{id}/versions` (each with why it was made, its
quality in short); `/assembled?version=` or `?at=<instant>` (one whole — as
it stood then); `/diff?from=&to=` (what changed); `/checks` (each time it
was made again, and what came of it).

**Quality, and saying something of it.** `GET /context/{id}/quality` — a
version's quality, whether the context is up to date now, what people said;
`POST /context/{id}/feedback` — `{ref_id, verdict: useful|not_useful|wrong}`
or `{verdict: missing, note}`; `GET /context/feedback?days=` — what people
said, counted by the retrievers that found it.

## 5. Following a context as it changes

`GET /api/v1/context/{id}/events` streams **server-sent events**
(`text/event-stream`) — what a browser's `EventSource` reads, with
`withCredentials: true` for the session:

```text
retry: 3000

event: freshness
data: {"state":"fresh","reasons":[],"since":null,"changes":0,…,"version":1}

id: 2026-10-05T14:02:11.204+00:00
event: check
data: {"checked_at":"…","trigger":"changed","checked_by":null,"change_count":2,"outcome":"version","version":2,…}

: keep-alive

event: bye
data: {"after":"2026-10-05T14:02:11.204+00:00"}
```

| Event | |
|---|---|
| `freshness` | whether it is up to date — at once, then each time that changes |
| `check` | each time it was made again: why, by whom (none: LEKA followed the model), what came of it — `id` is the cursor |
| `archived`, `gone`, `revoked` | the end: archived; deleted; the person no longer a member |
| `bye` | the stream's time is up (`?timeout=` seconds, 1 to 300, default 60): reconnect |

**Resuming.** A reconnecting `EventSource` sends `Last-Event-ID`; the
stream tells only what came after it. Without one, `?after=<instant>`, or
nothing — then only what happens from now. **Nothing is missed** between
two streams.

**What it costs, and what it holds.** It looks every 2 seconds in a session
of its own — it holds no transaction open — and, at every look, asks
whether the person is still a member: removing them ends the stream at the
next look, as it ends their next request. A quiet stream says
`: keep-alive` every 15 seconds, so proxies do not close it.

The **Contexte** tab of an entity listens to it: LEKA making the context
again on its own (LEKA-374) is said — « LEKA a mis ce contexte à jour :
version N » — and what the tab shows is read again.

## 6. On the screens

The **Contexte** tab of an entity's sheet: every version and how it was
made (`/versions`, `/assembled`, `/diff`), how good it is (`/quality`),
each element opened — how it stood in each version, what quality says of
it, and, on asking, **Voir les preuves**: the records it was read from
(`/elements/{ref}`, `/evidence`). Archiving and *Suivre le modèle* are
offered to its maker and admins only; the rest to every member who may
make contexts.

## 7. Security, in short

- **Tenancy is structural**: a context, its versions, elements, checks and
  feedback are tied to their workspace by composite foreign keys
  ([context.md](context.md) § 12); every query is scoped to the session's.
- **404, never 403, across workspaces**: whether a context exists elsewhere
  is not said.
- **Least privilege**: reading the records behind an element takes
  `source:read` too; ending what everyone reads — archiving, unfollowing —
  takes being its maker or an admin.
- **Long-lived reads re-check**: a stream re-reads membership at every
  look (§ 5).
- **The contract is held**: a client that would misread another version is
  refused before anything happens (§ 3).

## 8. From LEKA's own services, in Python

```python
from leka.context import ContextService, ContextRepository, IntentAsk
from leka.knowledge import GraphService, GraphRepository
from leka.ingestion import ContentRepository

service = ContextService(
    ContextRepository(session, workspace_id),
    GraphService(GraphRepository(session, workspace_id)),
    content=ContentRepository(session, workspace_id),
)
made = await service.assemble_intent(IntentAsk(text="…"), by=user_id)
quality = made.quality                       # how sure to be, what is missing
element = await service.inspect_element(made.context_id, ref_id)
evidence = await service.evidence(made.context_id, ref_id)
contract = ContextService.contract()        # the same as GET /context/contract
```

The service does not check permissions — a route does, with a dependency
(architecture rule 5). A service calling it acts for someone who may.
