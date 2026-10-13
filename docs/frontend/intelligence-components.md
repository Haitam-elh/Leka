# Intelligence components (LEKA-341)

How LEKA's reasoning results look — what an analysis comes to, the context
it used, what it found, what it thinks caused it, the evidence, what it
reaches, what it proposes, how sure it is and on what, what it does not
know — the same way on every screen, as the intention mockups draw them
(`docs/product/mockups/03` to `06`, and `11` for an entity's sheet). The
code is in [`web/components/intelligence/`](../../web/components/intelligence/),
exported from its `index.ts`; the shapes are in
[`web/lib/intelligence.ts`](../../web/lib/intelligence.ts). Every component,
and an analysis in each of its states, is on the development gallery at
**`/_dev/intelligence`**.

Four rules hold for all of them:

- **What kind of statement a line is, it says.** A fact — a source said
  it, LEKA observed it — is a line tagged *Constat*. A probable cause —
  what LEKA thinks — is a line tagged *Cause déclarée* (a source says so),
  *Cause probable* (LEKA thinks so, fairly sure) or *À confirmer* (LEKA
  only suspects it), with how sure, always. A recommendation — what LEKA
  proposes, someone decides — is a card with its priority and a box to
  tick, and no such tag. The types keep them apart too (`Finding`,
  `ProbableCause`, `Recommendation`): no screen can hand one to the
  component of another.
- **Every statement can be opened on its evidence.** *Voir les éléments
  (N)* on a line opens its evidence in place; each piece says what it is,
  the tool it was read from and when, *Voir* goes to it whole (a new tab
  when it lives in its tool), and its details — its key, its record, the
  rule — open under it.
- **Confidence and impact are words, never only a colour.** *● Confiance
  élevée · 90 % · déclaré par la source*; *Confiance inconnue* when nothing
  said how sure — never a made-up number. *Impact global: Inconnu* when
  nothing says how bad — never low.
- **Nothing is invented.** A screen maps what its API says onto the shapes
  and says what is missing; where LEKA cannot produce something yet, the
  section says so (*LEKA ne propose pas encore de recommandation*), or the
  screen says it is an example before anything else (`ExampleNotice`).

## The mockups, component by component

| Mockup | What it shows | Component |
|---|---|---|
| 03 *Analyse en cours…* | the analysis still running | `AnalysisState` `running` |
| 03 *Premiers constats* | tinted lines, a tag, *Voir les éléments* | `FindingList`, `ProbableCauseList` |
| 03, 05 *Niveau de confiance*, *Confiance de l'analyse* | *● Élevée*, and the lines it rests on, ticked or still missing | `ConfidencePanel`, `SupportList`, `ConfidenceBadge` — and, for a context, with what LEKA judged of it (LEKA-375): `QualityPanel` in `components/environment/context-quality.tsx` |
| 04 *Synthèse de l'analyse* | what it comes to, how sure, on what | `AnalysisSummary` |
| 04 *Preuves et sources clés* | a line per piece, *Voir*, *Voir toutes les preuves (N)* | `EvidenceList` (`max`) |
| 04, 05 *Services impactés*, *Impact global* | the level in a word, then what it concerns, a line each | `ImpactPanel` under a section titled *Impact global* |
| 04, 05 *Recommandations de LEKA* | a card each: icon, priority, chips, chevron | `RecommendationCard`, `RecommendationList` |
| 05 *Éléments qui justifient cette recommandation* | the first pieces side by side, then all | `EvidenceStrip` |
| 02, 05, 06 *Vous gardez le contrôle* | nothing runs without a yes | `ControlNotice` |
| 11 *Analyse de LEKA* | a band: what it comes to, *Voir l'analyse complète* | `components/environment/incident-analysis.tsx` |

## The order of an analysis

`AnalysisView` draws an `Analysis` as mockup 04 lays it out, in the one
order every output keeps:

1. **How it went** — `AnalysisState`: nothing when complete; *Analyse en
   cours…*, what was found so far shown under it; *Analyse partielle* and
   what is missing; *Analyse non concluante*; *L'analyse a échoué* (an
   alert, with *Réessayer*); *Pas encore d'analyse*.
2. **What it comes to, and how sure** — `AnalysisSummary`: the synthesis,
   the confidence and what it rests on. Left out (`synthesis={false}`)
   where the screen already says it, as an incident's band; its confidence
   then heads the right side as a `ConfidencePanel`.
3. On the left, **what is known** — *Constats*, `FindingList`; **what is
   thought** — *Causes probables*, `ProbableCauseList`, the surest first;
   **what it rests on** — *Preuves et sources clés*, every piece once
   (`evidenceOf`), the first five, then all.
4. On the right, **what it reaches** — *Impact global*, `ImpactPanel`, its
   level and what it is read from, then area by area (touched, what
   depends on it, applications, business), empty areas left out; **what
   LEKA proposes** — *Recommandations de LEKA*, apart; **what it does not
   know** — `UncertaintyList`.

Two columns from 1280 px, one under it in that same order. A failed or
pending analysis draws its state and nothing else: no empty sections
pretending to be results.

## Which component, when

| Component | For | Notes |
|---|---|---|
| `IntelligenceSection` | any part of an output | a card: its icon by `kind` (`fact`, `hypothesis`, `proposal`, `evidence`, `impact`, `confidence`, `context`), its title, `count`, `subtitle`, `action`; `level`: its heading's, 2 under a page title, 3 under a section's (axe checks the order) |
| `Pill` | a tag, a priority, a chip | a word, the colour only repeating it |
| `ConfidenceBadge` | how sure, anywhere | high ≥ 85 %, medium ≥ 60 %, low below, unknown when none (`confidenceLevel`); `basis`: stated or inferred; `short` under a heading that says *Confiance*; `level`: the level the analysis says, with why (LEKA-441) — then a word, no percentage |
| `ConfidencePanel`, `SupportList` | how sure an analysis is, and on what | `Support`: a line, established or still missing; with a `definition` (LEKA-441) it opens on what it counts and its `refs` — a figure nothing defines is not said |
| `UnderstoodLine` | what LEKA understood (LEKA-441) | above the results |
| `ConfidenceExplained` | how sure, in words, and why | each reason: its starting point, what caps it |
| `SourcesConsulted` | the sources an analysis read from | each in its state: *Lue*, *En échec*, *Dégradée*, *Pas à jour*, *Synchro en cours*, *Désactivée*, *Supprimée* — never *Lue* when it was not |
| `ConflictList` | what the sources contradict about what is asked | every side, who says it; nothing when none |
| `AnalysisLimits` | what did not answer and what that leaves unknown, what may be out of date | *Rien n'a manqué* when nothing did |
| `NextStepPanel` | what to do next, and why | `action` takes the screen's way to do it |
| `FreshnessNotice` | a context that moved on since the analysis read it | `action` takes *Relancer*; nothing when it is the latest |
| `UncertaintyList` | what is not known | draws nothing when empty |
| `EvidenceList`, `EvidenceStrip`, `EvidenceButton`, `EvidenceToggle` | the evidence of a statement | a piece: `record`, `entity`, `event`, `inference`; its source's logo, its date; *Voir* named by what it opens; details with `aria-expanded` |
| `FindingList` | facts | `title` when the statement is long |
| `ProbableCauseList` | hypotheses | tag from `causeTag()` — with `strength` (LEKA-441): *Cause déclarée* (confirmed), *Cause probable*, *Corrélation, pas une cause* (no percentage) — confidence, *Pourquoi*, evidence |
| `ImpactPanel`, `RiskBadge` | what it reaches, how bad | `riskOf()` reads a tool's severity or priority — sev1/P1/critical high, sev2/P2/major medium, sev3–5/minor low, else unknown |
| `RecommendationCard`, `RecommendationList` | proposals | `priority`, `action` (its icon), chips: what it touches, `effort`, *Réversible*/*Irréversible*, risk, confidence, *Pas exécutable en l'état* (LEKA-441) and *À régler d'abord*; the chevron opens what it needs first (`preconditions`), what it assumes (`assumptions`) and what justifies it; `control` takes a checkbox — acting asks first (`components/interactions/confirm`); `compact` in a side column |
| `ControlNotice` | a screen where a yes runs something | — |
| `AnalysisState` | how it went | running, partial, inconclusive, failed (`role="alert"`, retry), pending |
| `AnalysisSummary` | what it comes to | — |
| `AnalysisView` | an analysis, whole | the order above |
| `ContextUsedPanel`, `ContextVersionLine` | the context an output was made from (LEKA-370/371) | figures, how it was searched retriever by retriever, and what that leaves uncertain |
| `ExampleNotice` | a screen showing outputs LEKA cannot produce yet | first, before anything else |

## Where they are used

- **An incident's sheet** — *Analyse de LEKA*
  (`components/environment/incident-analysis.tsx`), mockup 11's band: what
  the analysis comes to in a few sentences and *Voir l'analyse complète*,
  which unfolds it in place as mockup 04. A partial or inconclusive
  analysis says so without being unfolded; a failed read is an alert at
  once, with *Réessayer*. The analysis is the incident as the company
  model knows it (`GET /knowledge/incidents/{id}`, LEKA-367), read by
  `lib/incident-analysis.ts`: its state and how long it lasted from its
  sources; its probable causes, said or suspected, the surest first, with
  what changed just before it; what it reaches and its level read from its
  severity; what its confidence rests on — the sources read, its timeline,
  what changed before it, what is missing; what is only suspected or not
  known. Complete when it knows a cause and what is touched, partial when
  one is missing, inconclusive when neither. No recommendation: the model
  proposes none — the analysis engine will (LEKA-388). The records are
  named from the workspace's sources by id: a provenance's `kind` is its
  key's, not its tool's.
- **An entity's context** — tab *Contexte* (LEKA-370/371): its figures and
  retrieval as `ContextUsedPanel`, its version line, each element's
  confidence as `ConfidenceBadge`.
- **The decision step** of a new intention (`/intentions/new?step=decision`),
  mockup 05: the recommendations as cards to tick, then `ControlNotice`;
  beside them the impact, a `ConfidencePanel` and the next steps; the
  selection bar across the page, approval asking first and saying what it
  affects. Everything on it is an example until the analysis engine
  proposes its own (LEKA-388, decisions LEKA-390), and the step says so
  first; each piece of evidence says *Exemple*.
- **The first step** of a new intention (mockup 02) offers the workspace's
  own sources and scope, not the components: see
  [forms-and-interactions.md](forms-and-interactions.md).

## Accessibility and responsive behaviour

- Each section is a region named by its heading; heading levels follow the
  page's (`level`).
- Every disclosure — *Voir les éléments*, a piece's details, *Voir toutes
  les preuves*, a recommendation's chevron, *Voir l'analyse complète* — is
  a button with `aria-expanded`, its `aria-controls` set while what it
  opens is there; an analysis that failed is an `alert`, the other states a
  `status`.
- *Voir* links are named by what they open (*Voir OPS-1841*): ten links
  called *Voir* say nothing to a screen reader.
- Colour repeats a word and an icon, never replaces them; the confidence's
  dot and the support's ticks are decorative (`aria-hidden`), the words
  carry them. *Analyse en cours* spins only when motion is welcome
  (`motion-safe`).
- One column under 1280 px; lines, chips and evidence rows wrap; nothing
  scrolls sideways.
- Verified by axe (WCAG 2.1 A and AA, best practices) on an incident's
  analysis unfolded with evidence open, the decision step and the context
  tab, and at 1024 px for overflow (`web/e2e/accessibility.spec.ts`,
  `intelligence.spec.ts`, `responsive.spec.ts`).
