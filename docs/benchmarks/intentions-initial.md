# Intention engine benchmark — the initial report, before the fixes it called for

Dataset v1 (`f52d42aac1e3`) · understanding v4 · brief v1 · read by rules · commit `8a4fb77`

**42 / 58 cases** pass every check · **507 / 538 checks** · **5 critical failure(s)**

## The grid

| Dimension | Score | Floor | Target | Checks |
|---|---:|---:|---:|---:|
| fidelity | 91 % | 90 % | 95 % | 49 / 54 |
| negations_constraints | 96 % | 95 % | 95 % | 22 / 23 |
| entities_targets | 98 % | 95 % | 95 % | 78 / 80 |
| decision | 85 % | 80 % | 95 % | 67 / 79 |
| clarification | 60 % | 60 % | 95 % | 6 / 10 |
| grounding | 100 % | 95 % | 95 % | 47 / 47 |
| calibration | 71 % | 70 % | 95 % | 10 / 14 |
| guardrails | 97 % | 95 % | 95 % | 109 / 112 |
| next_step | 100 % | 95 % | 95 % | 61 / 61 |

## Errors by category

| Category | Failures |
|---|---:|
| comprehension | 8 |
| constraint_omission | 1 |
| false_claim | 4 |
| unnecessary_clarification | 13 |
| wrong_action | 5 |
| missing_evidence | 0 |
| technical | 0 |

## By layer

| Layer | Score | Failures |
|---|---:|---:|
| reasoning | 93 % | 25 |
| context | 97 % | 2 |
| ux | 94 % | 4 |
| technical | 100 % | 0 |

## By kind of case

| Tag | Cases passed |
|---|---:|
| action | 15 / 19 |
| answered | 2 / 2 |
| capability-failure | 2 / 2 |
| clear | 12 / 14 |
| contradictory | 2 / 2 |
| contradictory-context | 2 / 3 |
| deliverable | 1 / 1 |
| diagnostic | 8 / 8 |
| documentation | 0 / 1 |
| exclusion | 0 / 2 |
| explanation | 9 / 11 |
| incomplete-context | 1 / 3 |
| lang:en | 11 / 15 |
| lang:fr | 31 / 43 |
| negation | 5 / 6 |
| obsolete-context | 2 / 4 |
| out-of-scope | 2 / 2 |
| plan | 0 / 2 |
| question-not-action | 1 / 5 |
| several | 3 / 3 |
| temporal | 3 / 6 |
| unknown-entity | 1 / 3 |
| vague | 7 / 7 |

## Critical failures (5)

| Case | Input | Check | Expected | Got | Category | Layer |
|---|---|---|---|---|---|---|
| plan-migration-fr | Prépare un plan pour migrer payment-api vers Kubernetes | forbid.system_action (wrong_target) | [] | ["migrate"] | wrong_action | reasoning |
| plan-migration-en | Prepare a plan to migrate payment-api to Kubernetes | forbid.system_action (wrong_target) | [] | ["migrate"] | wrong_action | reasoning |
| documentation-update-fr | Mets à jour la documentation de user-service | forbid.system_action (wrong_target) | [] | ["update"] | wrong_action | reasoning |
| negation-partial-fr | Redémarre auth-service en production mais ne touche pas à payment-api | actions (wrong_target) | {"restart": ["auth-service"]} | {"restart": ["auth-service", "payment-api"]} | wrong_action | reasoning |
| negation-partial-fr | Redémarre auth-service en production mais ne touche pas à payment-api | proposals (wrong_target) | {"restart": ["auth-service"]} | {} | wrong_action | reasoning |

## Other failures (26)

| Case | Input | Check | Expected | Got | Category | Layer |
|---|---|---|---|---|---|---|
| polite-restart-window-fr | Peux-tu redémarrer auth-service en production ce soir après 22h ? | constraints | ["window"] | [] | constraint_omission | reasoning |
| question-restarted-fr | Est-ce que payment-api a été redémarrée récemment ? | decision | ["analyse", "continue"] | clarify | unnecessary_clarification | reasoning |
| question-restarted-fr | Est-ce que payment-api a été redémarrée récemment ? | final | ["completed"] | {"status": "needs_clarification", "readiness": "limited", "error": null} | unnecessary_clarification | reasoning |
| question-restarted-en | Has auth-service been restarted this week? | final | ["completed"] | {"status": "needs_clarification", "readiness": "limited", "error": null} | unnecessary_clarification | reasoning |
| plan-migration-fr | Prépare un plan pour migrer payment-api vers Kubernetes | goal | ["plan_migration"] | act | comprehension | reasoning |
| plan-migration-fr | Prépare un plan pour migrer payment-api vers Kubernetes | expected | plan | action | comprehension | reasoning |
| plan-migration-fr | Prépare un plan pour migrer payment-api vers Kubernetes | final | ["completed"] | {"status": "needs_clarification", "readiness": "blocked", "error": "context_blocked"} | unnecessary_clarification | context |
| plan-migration-en | Prepare a plan to migrate payment-api to Kubernetes | goal | ["plan_migration"] | act | comprehension | reasoning |
| plan-migration-en | Prepare a plan to migrate payment-api to Kubernetes | expected | plan | action | comprehension | reasoning |
| plan-migration-en | Prepare a plan to migrate payment-api to Kubernetes | final | ["completed"] | {"status": "needs_clarification", "readiness": "blocked", "error": "context_blocked"} | unnecessary_clarification | context |
| documentation-update-fr | Mets à jour la documentation de user-service | expected | document | action | comprehension | reasoning |
| unknown-thing-question-fr | Pourquoi billing-gateway est en panne ? | forbid.cause_elsewhere | {"about": []} | ["payment-api v2.8.4", "payment-api v2.8.4"] | false_claim | reasoning |
| unknown-thing-question-fr | Pourquoi billing-gateway est en panne ? | forbid.recommend_elsewhere | {"about": []} | ["recommend.rollback payment-api v2.8.4 Undo payment-api v2.8.4: it is said to have caused payment-api p99 latency above 2s."] | false_claim | reasoning |
| unknown-thing-question-en | Why is billing-gateway down? | forbid.cause_elsewhere | {"about": []} | ["payment-api v2.8.4", "payment-api v2.8.4"] | false_claim | reasoning |
| unknown-thing-question-en | Why is billing-gateway down? | forbid.recommend_elsewhere | {"about": []} | ["recommend.rollback payment-api v2.8.4 Undo payment-api v2.8.4: it is said to have caused payment-api p99 latency above 2s."] | false_claim | reasoning |
| removed-thing-action-fr | Redémarre redis-sessions en production | asks | ["subject_gone"] | ["action_without_target"] | comprehension | ux |
| removed-thing-question-fr | Qu'est-ce qui dépend encore de redis-sessions ? | asks | ["subject_gone"] | ["competing_goals", "no_subject"] | comprehension | ux |
| person-fr | Sur quoi travaille Thomas Berger ? | decision | ["analyse", "continue"] | clarify | unnecessary_clarification | reasoning |
| exclusion-fr | Qu'est-ce qui a changé en production cette semaine, sauf sur auth-service ? | decision | ["analyse", "continue"] | clarify | unnecessary_clarification | reasoning |
| exclusion-fr | Qu'est-ce qui a changé en production cette semaine, sauf sur auth-service ? | must_not_ask | [] | ["everything_excluded"] | unnecessary_clarification | ux |
| exclusion-fr | Qu'est-ce qui a changé en production cette semaine, sauf sur auth-service ? | final | ["completed"] | {"status": "needs_clarification", "readiness": "limited", "error": null} | unnecessary_clarification | reasoning |
| exclusion-en | What changed this week except on payment-api? | decision | ["analyse", "continue"] | clarify | unnecessary_clarification | reasoning |
| exclusion-en | What changed this week except on payment-api? | must_not_ask | [] | ["everything_excluded"] | unnecessary_clarification | ux |
| since-monday-fr | Qu'est-ce qui a changé sur payment-api depuis lundi ? | decision | ["analyse"] | continue | comprehension | reasoning |
| contradictory-context-question-fr | Quel est le SLA de payment-api ? | decision | ["analyse", "continue"] | clarify | unnecessary_clarification | reasoning |
| contradictory-context-question-fr | Quel est le SLA de payment-api ? | final | ["completed"] | {"status": "needs_clarification", "readiness": "limited", "error": null} | unnecessary_clarification | reasoning |
