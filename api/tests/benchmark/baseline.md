# Intention engine benchmark — report

Dataset v4 (`9395fa0a808d`) · understanding v6 · brief v1 · read by rules · commit `d406e60a`

**71 / 71 cases** pass every check · **658 / 658 checks** · **0 critical failure(s)**

## The grid

| Dimension | Score | Floor | Target | Checks |
|---|---:|---:|---:|---:|
| fidelity | 100 % | 95 % | 95 % | 62 / 62 |
| negations_constraints | 100 % | 95 % | 95 % | 30 / 30 |
| entities_targets | 100 % | 95 % | 95 % | 102 / 102 |
| decision | 100 % | 95 % | 95 % | 87 / 87 |
| clarification | 100 % | 95 % | 95 % | 10 / 10 |
| grounding | 100 % | 95 % | 95 % | 74 / 74 |
| calibration | 100 % | 95 % | 95 % | 22 / 22 |
| guardrails | 100 % | 95 % | 95 % | 121 / 121 |
| next_step | 100 % | 95 % | 95 % | 79 / 79 |

## Errors by category

| Category | Failures |
|---|---:|
| comprehension | 0 |
| constraint_omission | 0 |
| false_claim | 0 |
| unnecessary_clarification | 0 |
| wrong_action | 0 |
| missing_evidence | 0 |
| technical | 0 |

## By layer

| Layer | Score | Failures |
|---|---:|---:|
| reasoning | 100 % | 0 |
| context | 100 % | 0 |
| ux | 100 % | 0 |
| technical | 100 % | 0 |

## By kind of case

| Tag | Cases passed |
|---|---:|
| action | 25 / 25 |
| answered | 2 / 2 |
| capability-failure | 2 / 2 |
| clear | 17 / 17 |
| contradictory | 2 / 2 |
| contradictory-context | 3 / 3 |
| deliverable | 1 / 1 |
| diagnostic | 10 / 10 |
| documentation | 1 / 1 |
| exclusion | 4 / 4 |
| explanation | 12 / 12 |
| incomplete-context | 3 / 3 |
| lang:en | 19 / 19 |
| lang:fr | 52 / 52 |
| negation | 9 / 9 |
| obsolete-context | 4 / 4 |
| out-of-scope | 2 / 2 |
| plan | 3 / 3 |
| question-not-action | 9 / 9 |
| several | 4 / 4 |
| temporal | 8 / 8 |
| unknown-entity | 4 / 4 |
| vague | 7 / 7 |

## Critical failures (0)

None.

## Other failures (0)

None.
