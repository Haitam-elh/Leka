# The capability router (LEKA-398)

Which of LEKA's capabilities an intention goes to — so that people say the
outcome they want, never which agent or analysis should do it. Code:
`api/leka/capabilities/router.py` (pure: the signals, the policy, the
decision), `CapabilityRouter` in `service.py` (for a workspace and a person,
kept), `api/leka/intentions/routing.py` (what the router reads of an
intention); the routes in `api/leka/api/intentions.py` and
`api/leka/api/capabilities.py`.

```
the intention, as understood (LEKA-385, 386)   goal, kind, a question or a
                                                request, what it is about,
                                                its words, whether it is clear
its context (LEKA-387)                          the types of the things it
                                                holds, the kinds of sources
the catalogue, for this person (LEKA-393)       each capability, usable here
                                                or not, and why
        │
        ▼
signals ──▶ ranked ──▶ excluded (unavailable, not permitted, a policy)
        ──▶ routed: the best, and those within a point · fallback: LEKA's
            analysis · clarify: what to ask, what it could mean
        ──▶ kept (capability_routings)
```

## 1. What it reads

| | From |
| --- | --- |
| `goal`, `kind`, `mode`, `acting` | the understanding: its goal, the kind of request, a question or a request, whether an action asked would change systems |
| `entity_types` | the types of what it is about (its scope, else its entities) |
| `text` | its words |
| `clear`, `questions` | the understanding: no blocking ambiguity; what LEKA would ask |
| `context_types`, `context_sources` | its context: the types of its entities, the kinds of the sources they came from |

Words routed without an intention (`POST /capabilities/route`) carry what
the caller says: words, a goal, a kind, a mode, types.

## 2. The signals

| Signal | Points | When |
| --- | --- | --- |
| `goal` | 3 | the capability answers its goal |
| `kind` | 2 | … its kind of request |
| `entity` | 1 each, 2 at most | it acts on a type the intention is about |
| `words` | 1 each, 3 at most | a word of four letters or more in common with its title, summary, examples (accents and case aside) |
| `context_types` | 1 | it is about a type its context holds |
| `context_sources` | 1 | every source it needs is one its context came from |
| `mode` | 1 | a request to act, and a capability that proposes actions |
| `deprecated` | −1 | deprecated: still usable, to be replaced |

**Eligible**: 3 points or more, on what is asked (`goal`, `kind`, `entity`
or `words`) — never on its context alone. Ranked by score, then by how many
kinds of signal, then by key. **Selected**: the best and those within one
point of it, three at most — so an intention may go to more than one.

## 3. Excluded, never routed to

- **Unavailable or not permitted** — the catalogue's reasons
  ([capabilities.md](capabilities.md) § 4): retired, refused, turned off,
  its source not connected, no model, the person's role lacks its
  permission. Each kept with its reasons.
- **A policy: a question never goes to a capability that proposes
  actions** — only a request to act does (`policy`,
  `proposes_actions_to_a_question`). What an agent proposes, a person
  decides (LEKA-390).
- **Run with every analysis** (`always`, the synthesis): not routed to, said
  `background`. Retired: never considered.

## 4. The outcome

| `outcome` | When | `why` |
| --- | --- | --- |
| `routed` | an eligible capability: `selected` | |
| `fallback` | nothing eligible: **LEKA's own analysis** (`fallback: analysis`), which every intention gets | `no_match` — nothing fits better · `excluded` — a better one is left out, said in `excluded` |
| `clarify` | the intention is not clear, or nothing it says points anywhere and its goal is unknown | `unclear` (its `questions`) · `no_goal`; `suggestions`: what it could mean, the best candidates |

A selected **agent** says what it must be asked before it runs
(`needs_inputs`: its required inputs); run for the intention, it reads the
intention's context ([agent-runtime.md](agent-runtime.md) § 3).

## 5. Kept

`capability_routings` — one per decision: the intention (or `request`), the
version of the rules (`ROUTING_VERSION`), what the router read, the outcome,
what it selected, every candidate with its score, signals, availability and
the inputs it needs, every one excluded with why, what runs in the
background, the fallback, the questions and suggestions, who routed it,
when. **Routed again, a new row** beside the earlier.

## 6. The API

| Route | | Permission |
| --- | --- | --- |
| `GET /intentions/{id}/routing` | its latest routing — routed now, for the reader, when it never was | `intention:read` |
| `POST /intentions/{id}/routing` | routed again, as it and the catalogue now stand | `intention:create` |
| `POST /capabilities/route` `{text, goal?, kind?, mode?, entity_types?}` | where these words would go, for this person — kept | `workspace:read` |

Routed for whoever asks: what they may not use is excluded from **their**
routing.

## 7. In the app

On an intention's overview, **Capacité choisie**: what LEKA chose and why
in words — each capability considered with its score and signals, each one
left out and why, LEKA's analysis when nothing fits better, what to ask when
it is not clear — and **Router à nouveau**. A chosen agent is offered to run
for the intention (**Lancer l'agent**), asking what it needs.

## Not yet

- **Running what is routed to on its own**: the analysis runs LEKA's own
  capabilities by goal and kind; an agent or a workflow
  ([workflows.md](workflows.md)) is offered, a person runs it —
  orchestrating several without a workflow (LEKA-399).
- Signals learned from use (what people ran after a routing).
