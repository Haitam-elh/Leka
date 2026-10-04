# Intelligence components (LEKA-341)

How LEKA's reasoning results look — the context it used, what it found,
what it thinks caused it, the evidence, what it reaches, what it proposes,
how sure it is and what it does not know — the same way on every screen.
The code is in [`web/components/intelligence/`](../../web/components/intelligence/),
exported from its `index.ts`; the shapes are in
[`web/lib/intelligence.ts`](../../web/lib/intelligence.ts). Every component,
and an analysis in each of its states, is on the development gallery at
**`/_dev/intelligence`**.

Four rules hold for all of them:

- **A fact, a hypothesis and a proposal never look alike.** A finding — a
  source said it, LEKA observed it — sits in a plain card tagged *Constat*.
  A probable cause — what LEKA thinks — in an amber one tagged *Hypothèse*,
  with how sure. A recommendation — what LEKA proposes, someone decides — in
  a dashed violet one tagged *Proposition de LEKA*. The types keep them
  apart too (`Finding`, `ProbableCause`, `Recommendation`): no screen can
  hand one to the component of another.
- **Every statement can be opened on its evidence.** "N preuve(s)" under a
  finding, a cause or a recommendation opens the list; each piece says what
  it is, the tool it was read from and when, and opens on what it holds —
  its key, its record, the rule — with a link to see it whole.
- **Confidence and risk are words, never only a colour.** *Confiance élevée
  · 90 % · déclaré par la source*; *Confiance inconnue* when nothing said
  how sure — never a made-up number. *Risque inconnu* when nothing says how
  bad — never low.
- **Nothing is invented.** A screen maps what its API says onto the shapes
  and says what is missing; where LEKA cannot produce something yet, the
  section says so (*LEKA ne propose pas encore de recommandation*), or the
  screen says it is an example before anything else (`ExampleNotice`).

## The order of an analysis

`AnalysisView` draws an `Analysis` in the one order every output keeps:

1. **How it went** — `AnalysisState`: nothing when complete; *Analyse
   partielle* and what is missing; *Analyse non concluante*; *L'analyse a
   échoué* (an alert, with *Réessayer*); *Pas encore d'analyse*.
2. **How sure, as a whole** — `ConfidenceBadge`.
3. **What is known** — `FindingList` in a *Constat* section.
4. **What is thought** — `ProbableCauseList` in a *Hypothèse* section,
   beside the facts on a large screen, under them on a small one.
5. **What it reaches** — `ImpactPanel`: the risk and what it is read from,
   then area by area (touched, what depends on it, applications, business),
   empty areas left out.
6. **What LEKA proposes** — `RecommendationList` in a *Proposition* section,
   apart and below.
7. **What LEKA does not know** — `UncertaintyList`.

A failed or pending analysis draws its state and nothing else: no empty
sections pretending to be results.

## Which component, when

| Component | For | Notes |
|---|---|---|
| `IntelligenceSection` | any part of an output | `kind`: `fact`, `hypothesis`, `proposal`, `evidence`, `context`; `level`: its heading's, 2 under a page title, 3 under a section's (axe checks the order) |
| `ConfidenceBadge` | how sure, anywhere | high ≥ 85 %, medium ≥ 60 %, low below, unknown when none (`confidenceLevel`); `basis`: stated or inferred |
| `UncertaintyList` | what is not known | draws nothing when empty |
| `EvidenceList`, `EvidenceToggle` | the evidence of a statement | a piece: `record`, `entity`, `event`, `inference`; its source's logo, its date; opens with `aria-expanded` |
| `FindingList` | facts | each with its evidence |
| `ProbableCauseList` | hypotheses | ranked *Hypothèse 1, 2…*, confidence, *Pourquoi*, evidence |
| `ImpactPanel`, `RiskBadge` | what it reaches, how bad | `riskOf()` reads a tool's severity or priority — sev1/P1/critical high, sev2/P2/major medium, sev3–5/minor low, else unknown |
| `RecommendationCard`, `RecommendationList` | proposals | why, effect, risk, *Réversible*/*Irréversible*, confidence, evidence; `control` takes a checkbox to choose it — acting asks first (`components/interactions/confirm`) |
| `AnalysisState` | how it went | partial, inconclusive, failed (`role="alert"`, retry), pending |
| `AnalysisView` | an analysis, whole | the order above |
| `ContextUsedPanel`, `ContextVersionLine` | the context an output was made from (LEKA-370/371) | figures, how it was searched retriever by retriever, and what that leaves uncertain — a retriever that failed, things the budget left out |
| `ExampleNotice` | a screen showing outputs LEKA cannot produce yet | first, before anything else |

## Where they are used

- **An incident's sheet** — *Analyse de LEKA*
  (`components/environment/incident-analysis.tsx`): the incident as the
  company model knows it (`GET /knowledge/incidents/{id}`, LEKA-367), read
  as an analysis by `lib/incident-analysis.ts` — its state and how long it
  lasted from its sources; its probable causes, said or suspected, the
  surest first, with what changed just before it; what it reaches and the
  risk read from its severity; what is only suspected or not known.
  Complete when it knows a cause and what is touched, partial when one is
  missing, inconclusive when neither. No recommendation: the model proposes
  none — the engine will (LEKA-384). The records are named from the
  workspace's sources by id: a provenance's `kind` is its key's, not its
  tool's.
- **An entity's context** — tab *Contexte* (LEKA-370/371): its figures and
  retrieval as `ContextUsedPanel`, its version line, each element's
  confidence as `ConfidenceBadge`.
- **The decision step** of a new intention (`/intentions/new?step=decision`):
  its recommendations as `RecommendationCard`s to tick, in a *Proposition*
  section, approval asking first and saying what it affects — under an
  `ExampleNotice` until the analysis engine proposes its own.

## Accessibility and responsive behaviour

- Each section is a region named by its heading; heading levels follow the
  page's (`level`).
- Every disclosure — a piece of evidence, "N preuve(s)" — is a button with
  `aria-expanded`; an analysis that failed is an `alert`, the other states a
  `status`.
- Colour repeats a word and an icon, never replaces them; the confidence's
  bars are decorative (`aria-hidden`), its words carry it.
- Facts and hypotheses sit side by side from 1024 px, one under the other
  below; evidence and impact rows wrap; nothing scrolls sideways.
- Verified by axe (WCAG 2.1 A and AA, best practices) on an incident's
  analysis with evidence open, the decision step and the context tab, and
  at 1024 px for overflow (`web/e2e/accessibility.spec.ts`,
  `intelligence.spec.ts`, `responsive.spec.ts`).
