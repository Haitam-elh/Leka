# Vue d'ensemble and Mon environnement: the Digital Twin (LEKA-442)

Two screens, one rule: **what needs someone is understood in a few
seconds, and every figure says where it comes from**. Every figure comes
from the connected environment. Nothing is invented: no state, no
real-time claim, no simulated alert.

The rules behind the states, the freshness and the alerts live in
[enrichment.md § 12 bis](../enrichment.md). This page says what the
screens show, in what order, and why.

## 1. Vue d'ensemble — the information hierarchy

`web/components/overview/overview.tsx`, top to bottom.

| Block | The question it answers | What it lets you do | Definition and provenance |
|---|---|---|---|
| Greeting, one sentence | « Is anything wrong right now? » | Read the page in one line | The twin first: elements `unavailable` or `degraded` (`GET /ingestion/enrichment/environment`, `states`); then a late read (`freshness.late`); then sources needing a look (`GET /sources`) |
| **Nouvelle intention** (the composer) | « What do I want to know or do? » | Ask LEKA | — |
| **À valider** | « What waits on my decision? » | Open the decision, the conflict or the proposal | The decisions, conflicts and enrichments waiting (LEKA-380, 382, 390) |
| **Ce qui ne va pas** | « What is in trouble, and how do we know? » | Open the element's sheet, or **Analyser** (an intention about it) | The twin's elements `unavailable` or `degraded`, the worst first, each with how it is known: the incident, measured, by which source, how sure. The elements with no signal are counted apart, « ce n'est pas sain ». Alerts: on a paid plan, how many are open; on Free, the plan that includes them (`GET /monitoring`) |
| **Mes intentions en cours** | « Where are my requests? » | Open the intention | The active intentions (`GET /intentions?phase=active`) and their status |
| **Activité récente** | « What changed lately? » | Open what changed | What Activité tells: the same events, worded the same way (LEKA-438) |
| **Fraîcheur et couverture** | « Can I trust what LEKA sees? » | Open Sources | When the sources were last read and how often (never « temps réel »), the sources failing, late or never read, and what no source covers. When everything is read and covered, it says so in one line |
| **Insights LEKA** | « What did LEKA conclude? » | Open a finding | LEKA's two latest insights (LEKA-377) |

**Removed, and why** (before → after):

| Before | Why it went | Where the information is now |
|---|---|---|
| « État de votre environnement »: 4 KPI tiles, ~250 px of empty space (UX audit T1), « ? Services opérationnels » | Figures with no action, and an unknown that read like health | « Ce qui ne va pas » (what to act on) and the greeting |
| « Sources connectées »: every source, 5 rows | Healthy sources do not need you | « Fraîcheur et couverture » shows only what fails, plus the freshness |

**Density.** Before, the page had 4 KPI tiles with 4 footnotes, 6 cards and up to 13 list rows, including 5 healthy sources. After, it has 0 KPI tiles and 6 cards, each led by its question, and only the rows that need someone. Each list is capped at 4 or 5.

Nothing essential is lost:
- elements in trouble are listed one by one, and the greeting counts them;
- what nothing says is said once;
- the sources that fail are named;
- the full lists stay one click away (Mon environnement, Sources, Activité, Intentions).

## 2. Mon environnement — the Digital Twin

`web/components/environment/environment-screen.tsx` and `twin.tsx`.

**At first sight** (readable, details on click):
- **Header**: when the sources were last read, how often, and « pas en temps réel ». A late read is said late.
- **The tab bar**: the six states, each defined. The definition shows on hover and is read by screen readers.
- **État de l'environnement**: how many elements are in each state. **Each count opens the list of those elements.**
- **The architecture** (the map) or **the list**: the map/list switch is in the header. Every card's state is the twin's (`withTwin`), by entity id, so it is the same as on the list and on a sheet.
- Below:
  - **Alertes**, or the plan's limit;
  - **Sources et couverture**;
  - what moved, and points of attention.

**Exploring:**

| From | Click | You get |
|---|---|---|
| The map | an element | its panel: kind, the twin's state, links, and the way to its sheet (LEKA-369) |
| A count | a state | the list filtered to it |
| The list | a name | the element's sheet |
| The list | « Demander à LEKA » | a new intention about it, pre-written |
| A sheet | — | its state, how it is known, when it was last observed, and **each source showing it, in its state**; its dependencies, incidents and activity (LEKA-359) |
| An alert | « Analyser avec LEKA » | a new intention about the trouble. A sensitive remediation still goes through approval (LEKA-390) |
| The map's « Cartographie détaillée » | — | the whole graph, zoomable (LEKA-369) |

**A readable alternative.** When the map is too dense, **the list** shows
every element with a state:
- the worst first;
- its state, and where that state comes from;
- when it was last observed;
- the way to ask LEKA about it.

The list can be filtered by state, and sorted.

## 3. How states and freshness are shown

- **Six states, six words, everywhere**: Indisponible (red), Dégradé (orange), Données obsolètes (blue, a clock), Inconnu (grey, a question mark), Non couvert (grey, crossed out) and Opérationnel (green).
  - The colour only repeats the word.
  - « Inconnu » and « Non couvert » are never green.
- **How it is known** goes next to every state:
  - the reason (« incident OPS-1841 ouvert », « surveillé, rien à signaler », « aucun outil de supervision connecté »);
  - the basis: mesuré, déclaré par son fournisseur, déduit;
  - by which source;
  - and when it is not confirmed: soupçonné, non vérifié.
- **A stale state says what it was**: « non vérifié · était opérationnel ».
- **Freshness**:
  - « Lu il y a 7 min · Sources lues toutes les 60 min — pas en temps réel »;
  - « En retard : aucune lecture depuis plus de 2 h »;
  - « certaines envoient leurs événements dès qu'ils arrivent » for webhook sources.
- **Sources**: each source is shown as Lue, En échec (with its error), Dégradée, Pas à jour, Synchro en cours, Désactivée or Jamais lue, with when it was last read.
- **Alerts**:
  - on a paid plan: each alert gives what is wrong, how sure, since when, when it was last seen, and the way to analyse it. Alerts that ended in the last 7 days show what verified them;
  - on Free: « La surveillance proactive n'est pas incluse dans votre plan », then what the plan does show and the plan that includes alerts. **Never an alert simulated, never a state hidden.**

## 4. Validation scenarios, with representative data

| Scenario | Data | Expected | Test |
|---|---|---|---|
| Empty environment | no source | « Connectez une première source », « Aucune source connectée », nothing in trouble | `overview.test.tsx` — invites a first source |
| Partially connected | GitHub read, Runbooks failing, no monitoring tool | payment-api degraded (incident), 2 elements with no signal, Runbooks « en échec », « Non couvert : État des services » | `overview.test.tsx` |
| Connected | read and covered | « Rien d'indisponible ni de dégradé », « Toutes les sources sont lues… » | `overview.test.tsx` |
| Normal state | Datadog watching, read 20 min ago | Opérationnel · mesuré · par acme-eu | `test_twin.py`, `test_monitoring_api.py`, `twin.test.tsx` |
| Confirmed incident | open sev1 | Indisponible · incident OPS-9 ouvert · confirmé | `test_twin.py`, `twin.test.tsx` |
| Suspected anomaly | deduced degraded | Dégradé · déduit · soupçonné | `test_twin.py`, `twin.test.tsx` |
| Unknown element | a monitoring tool connected, nothing on it | Inconnu · aucun signal, never green | `test_twin.py`, `twin.test.tsx` |
| Stale source | last read 5 h ago | Données obsolètes · était opérationnel · non vérifié | `test_twin.py`, `twin.test.tsx` |
| Unavailable source | error, failing sync | En échec, its error; its elements stale, « sources en échec » | `test_twin.py`, `twin.test.tsx` |
| Free plan | — | states seen, no alert opened, the limit and « dès Starter, par e-mail dès Growth » | `test_monitoring_api.py`, `twin.test.tsx`, `overview.test.tsx` |
| Paid plan with alerts | Growth, incident opened | 2 alerts (payment-api, Runbooks), 1 e-mail, never twice; resolved only when Datadog was read since | `test_monitoring_api.py`, `test_monitoring_alerts.py` |
| Capability not included | Starter: e-mail not included | alerts « dans LEKA », no e-mail | `test_monitoring_api.py`, `twin.test.tsx` |
| Element → intention | any troubled element or alert | a pre-written intention; its remediation needs approval | `twin.test.tsx` |
