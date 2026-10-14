# The new interface, at /v2 (Lot 6)

The product call of 2026-10-14 asked for a simpler LEKA — « deux écrans au
maximum, peu de boutons par écran ; un client doit comprendre sans vidéo
explicative » — built **beside** the current interface, so the two can be
shown and compared. It is a separate route: `/v2`. Nothing of the current
interface changes; the same session, workspace and API serve both.

The message it carries: « Connecte tes sources, puis demande ce que tu veux.
Si tu veux qu'on développe, on développe. Si tu veux qu'on teste, on teste. »

## The two screens

| Screen | Address | What is on it |
|---|---|---|
| Home | `/v2` | LEKA's logo, tied by a line to each source it reads (a source that needs a look is drawn so); one bar; under it, the person's active agents as chips — a click puts `/architecte` first in the request — and « Voir tous ». |
| Agents and bundles | `/v2/agents` | Lot 2's catalogue: each agent with its price, status and purchase; the bundles. Its « Demander » goes back to the home's bar. |

Around them:

- **Top right, the environment's health**: a dot and one word —
  « Environnement stable » (green), « Attention requise » (orange),
  « Incident » (red), or « Aucune source connectée ». Opened, the
  environment as monitoring read now and then: its sources and each one's
  state, what is wrong and how it is known, a detail on click. Not a page of
  the menu. `components/v2/health.tsx` (`healthOf`): red when an incident is
  open or something is unavailable; orange when something is degraded, the
  sources were not read on time, or a source fails, is degraded or late;
  green otherwise.
- **The avatar's menu**: Configuration (Sources, Sécurité, Équipe),
  Facturation, Historique, « Revenir à l'interface actuelle », Déconnexion —
  only what the person may open.
- **Historique** (`/v2/history`): the requests made, the latest first. It
  replaces « Mes intentions » in the main navigation. Opened again, the
  exchange carries on under the bar.

## The exchange

What is typed in the bar is asked at once — no « Pour affiner
(facultatif) », no « Lancer l'analyse », no « Suivre l'analyse ». The answer
comes under the bar, as a thread (`components/v2/thread.tsx`):

| Where LEKA is | What the thread says |
|---|---|
| reading (`ready`, `analysing`) | « LEKA lit vos sources et prépare sa réponse… », read again until it answers |
| a detail is missing (`needs_clarification`) | LEKA's questions, answered in place |
| answered (`decision_required`…) | the answer — its detail folded — then Lot 1's decision: the agents it takes, launched by the person, or « Je le fais moi-même »; a locked agent bought with Lot 2's checkout, which brings the person back to this thread (`back: "home"`) |
| at work (`approved`, `action_running`…) | the agents' work and deliverables, or the plan's checklist |
| failed | what happened, and « Relancer » |

While LEKA can take the exchange again (`ask_again`), what is typed next
is a detail added to it — a new version of the same intention, its text the
request then each detail, read back as the thread's lines. Once its agents
work on it, or it is closed, what is typed is a new request.

LEKA stays a specialist of the technical stack: a request about anything
else is said in words under the bar (Lot 0's `off_topic`), and every answer
rests on the connected sources.

## Gone, in the new interface

The dashboard, and its blocks « À valider », « Ce qui ne va pas », « Mise en
intention », « Activité récente », « Fraîcheur et couverture », « Insights »;
the environment's long menu; the sidebar. What they said is reached
otherwise: the health's dot, the thread, the avatar's menu.

## Switching it off

It is a route of its own, reached by its address only: the current
interface links to nothing in it. To take it away, delete `app/(v2)` and
`components/v2` — nothing else depends on them. The checkout's `back:
"home"` (`api/leka/billing/add_ons.py`) stays harmless: a closed choice,
never an address.
