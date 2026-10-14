# Acceptance scenario — the product call of 2026-10-14

The scenario the call asked to run once Lots 0 to 6 are merged, step by
step: what is expected, which lot brings it, and what already checks it
automatically. Run it on staging (or production with a test account),
Stripe in **test mode** only, and keep a capture of each step.

| # | Step | Expected | Lot | Checked automatically by |
|---|---|---|---|---|
| 1 | Create a new account from the landing (« Essayer gratuitement ») | The account is on **Free, 200 credits** | 4 | `test_a_new_workspace_starts_on_free_with_its_200_credits`; e2e `auth.spec.ts` |
| 2 | Onboarding: connect GitHub with an access token, wait for the full sync | The health indicator is **green** (« Environnement stable ») | 4, 6 | `v2.test.tsx` (`healthOf`); e2e `v2.spec.ts` |
| 3 | Type « Construis-moi l'architecture de l'application » | An answer; the agent **Architecte applicatif** proposed | 1 | `test_intention_agents.py`; e2e `intention-decide.spec.ts` |
| 4 | On Free | The agent is **locked**; LEKA offers Starter or the purchase; **no free run** | 2 | `test_agent_entitlements.py` (refused by the server: `plan_required`) |
| 5 | Move to Starter (Stripe test card 4242…) | Back from payment, the intention **restarts**, the Architect runs, the **PDF** can be downloaded | 2 | `test_opened_from_a_decision_its_agents_are_launched_once_paid`; `test_bought_from_the_new_home_s_thread_it_comes_back_to_it` |
| 6 | The evidence | It cites **GitHub files**; the confidence is consistent | 1 | `test_an_answer_resting_on_what_a_model_read_counts_its_sources` |
| 7 | Type a development request | A **bundle** is proposed; once validated, a real **PR or diff** can be opened | 1, 2 | `test_intention_agents.py`; code-change agent (#275) |
| 8 | Type an off-topic request | A **clear message** | 0 | `test_intention_model.py`, `compact-composer.test.tsx`, `v2.test.tsx` |
| 9 | Billing: click « Ne pas renouveler » | The **end date** is shown; « Réactiver le renouvellement » works | 3 | `test_billing_renewal.py`; `subscription-section.test.tsx` |
| 10 | The renames | « Compétences », « Configuration » at the bottom left, **no « Propriétaire » block** at the bottom left | 5 | `app-sidebar.test.tsx`; e2e `navigation.spec.ts` |

## What needs a person

Steps 2 (a real GitHub token and its sync), 5 (Stripe's own checkout page,
in test mode) and 7 (a PR opened on a real repository) touch services the
automated suite fakes. They are the ones to run by hand and capture.

## Both interfaces

Steps 3 to 8 can be run from the current interface (Mon Dashboard's bar, an
intention's steps) or from the new one at `/v2` (one bar, the answer under
it — `docs/frontend/ux-v2.md`). Running them on both is the comparison the
call asked for.
