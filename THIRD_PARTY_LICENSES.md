# Third-party code and skills

Every piece of code, content or skill imported from outside this repository is
recorded here.

**This is a licence obligation, not paperwork.** Apache 2.0 and MIT both allow
commercial use, and both require that copyright notices be kept. Apache 2.0
additionally requires that modified files carry a notice saying they were
changed. We cannot meet either requirement retroactively, once nobody
remembers where a file came from.

## What belongs here, and what does not

**Here**: code, content or a skill copied into this repository — a vendored
file, an adapted agent, a snippet lifted from a blog post. Anything a reader
of our source would mistake for ours.

**Not here**: packages installed by a manifest. `api/pyproject.toml` and
`web/package.json` already name every dependency and its version, and the
licence of each is resolvable from that. Duplicating fifteen entries by hand
would give us a second list that drifts from the first, and a drifting
licence list is worse than none.

The distinction is whether the code lives in our tree or in a lockfile.

## The rule

**Any pull request that imports third-party code or a skill adds its row
below. No exceptions.** A reviewer seeing imported code without a new row
requests changes.

For anything landing in `agents/vendor/`, this row is the *second*
requirement. The first is a line-by-line review of the skill: an agent is text
that becomes an instruction executed by a model with access to a customer's
production data. The full rule lives in `agents/README.md`.

## How to fill a row

| Column | What goes in it |
| --- | --- |
| **Source** | where it came from, with a link and the commit or version |
| **Licence** | Apache-2.0, MIT, BSD-3-Clause… as the project declares it |
| **What we took** | the files or the part, precisely. Not "some helpers" |
| **What we changed** | required by Apache 2.0. "Nothing" is a valid answer, write it |
| **Date** | when it was imported |

Keep the upstream `LICENSE` file alongside the imported code, and keep the
copyright header inside each file. Do not reformat an imported file in the
same commit that imports it — the diff has to show what we changed.

## Imported

<!--
Example row, kept commented so the shape is obvious. Copy it, uncomment it,
fill it in.

| [anthropics/skills](https://github.com/anthropics/skills) @ `a1b2c3d` | Apache-2.0 | `document-review/SKILL.md`, its front matter format | Rewrote the trigger description for LEKA entity types; removed the file-writing section, agents are read-only here | 2026-09-19 |
-->

| Source | Licence | What we took | What we changed | Date |
| --- | --- | --- | --- | --- |
| [emilkowalski/skills](https://github.com/emilkowalski/skills) @ `2d22863` | MIT — Copyright (c) 2026 Emil Kowalski; text in `third_party/licenses/emilkowalski-skills-MIT.txt` | Twelve skills, whole directories, into `.claude/skills/`: `emil-design-eng`, `animate`, `review-animations`, `improve-animations`, `find-animation-opportunities`, `animation-performance`, `animation-vocabulary`, `apple-design`, `mobile-native`, `break-ui`, `pick-ui-library`, `prototype`. Tooling for the team in Claude Code, not a LEKA agent and never shipped to a customer | The twelve copied unchanged. `.claude/skills/leka-designer/SKILL.md` is a derived work: written in French from `emil-design-eng`, `break-ui`, `apple-design` and `review-animations`, merged with LEKA's own rules (`docs/product/ux-audit.md`, `docs/frontend/design-system.md`); it credits them | 2026-10-13 |
| [Simple Icons](https://simpleicons.org) @ `13.21.0` (npm `simple-icons`) | CC0-1.0 | The SVG path of twenty-six marks — GitHub, GitLab, Bitbucket, Google Cloud, Google Drive, Linear, Asana, Trello, ClickUp, Jira, Confluence, Notion, Datadog, PagerDuty, Grafana, Splunk, Kibana, PostgreSQL, MySQL, MariaDB, Oracle, Supabase, MongoDB, GraphQL, Slack, Amazon Web Services — and each brand's hex colour, into `web/components/sources/source-logo.tsx` | Paths unchanged; wrapped in one React component that colours each with its brand hex. The marks remain their owners' trademarks, used to name the system a source connects to | 2026-09-25 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` and [garrytan/gstack](https://github.com/garrytan/gstack) @ `945ac30` | MIT — Copyright (c) 2026 Affaan Mustafa; Copyright (c) 2026 Garry Tan | The method of ECC's `agents/code-reviewer.md` (a gate before each finding, severity that needs its proof, confidence, zero findings allowed, false positives to skip) and of gstack's `review/SKILL.md` (scope drift: the scope said against the scope touched), into `agents/development/code-review/SKILL.md`, section « Sa méthode » | Rewritten in French for what LEKA sees — the pull requests and commits its sources give, never the diff; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [garrytan/gstack](https://github.com/garrytan/gstack) @ `945ac30` and [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` | MIT — Copyright (c) 2026 Garry Tan; Copyright (c) 2026 Affaan Mustafa | The method of gstack's `cso/SKILL.md` (the application model first, the attack surface census, severity / confidence / evidence kept apart, a supported finding against a labelled hypothesis, sibling cases, unknown reachability kept unknown, a report that opens on complete / partial / not assessed) and the OWASP categories and false positives of ECC's `agents/security-reviewer.md`, into `agents/security/security-review/SKILL.md`, section « Sa méthode » | Rewritten in French for the company model — no code read, no scanner, no reproduction (gstack's runtime and Docker parts left out); nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` | MIT — Copyright (c) 2026 Affaan Mustafa | The method of ECC's `agents/build-error-resolver.md` (the smallest fix that turns the build green, no refactor, no architecture change, nothing improved on the way), into `agents/development/build-fixer/SKILL.md`, section « Sa méthode » | Rewritten in French for what LEKA sees — the commits and pull requests its sources give, never the build logs; the TypeScript commands and fix table dropped; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` | MIT — Copyright (c) 2026 Affaan Mustafa | The method of ECC's `agents/architect.md` (trade-offs, red flags), `agents/code-architect.md` (the simplest design first), `agents/code-explorer.md` (entry points, layers) and `skills/change-impact/SKILL.md` (links proven, not guessed from names; the unverified said), into `agents/architecture/architecture-analysis/SKILL.md`, section « Sa méthode » | Rewritten in French for what LEKA sees — the company model's entities and dependencies, never the code; the design checklists, patterns catalogue and scalability plan dropped; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [garrytan/gstack](https://github.com/garrytan/gstack) @ `945ac30` and [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` | MIT — Copyright (c) 2026 Garry Tan; Copyright (c) 2026 Affaan Mustafa | The method of gstack's `document-generate/SKILL.md` and `document-release/SKILL.md` (a coverage map by the reader's need — reference, how-to, tutorial, explanation —, critical and common gaps, one need per page, the voice gate) and of ECC's `skills/architecture-decision-records`, `skills/living-docs-governance`, `skills/docs-governance` and `agents/doc-updater.md` (a decision recorded with its context and alternatives, one canonical source per fact, a document that disagrees with reality is flagged, not silently chosen), into `agents/documentation/documentation-assistant/SKILL.md`, section « Sa méthode » | Rewritten in French for what LEKA sees — the documents and the company model, never the code; the git, file-writing, CHANGELOG and VERSION steps dropped; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` and [garrytan/gstack](https://github.com/garrytan/gstack) @ `945ac30` | MIT — Copyright (c) 2026 Affaan Mustafa; Copyright (c) 2026 Garry Tan | The method of ECC's `agents/pr-test-analyzer.md` (behavioural coverage, gaps rated by impact) and `skills/test-collaboration/SKILL.md` (test levels, a contract between two sides, a defect turned into a test of its real shape, green CI is not behavioural evidence) and of gstack's `test-audit/SKILL.md` (what a green test does not prove), into `agents/development/test-analysis/SKILL.md`, section « Sa méthode » | Rewritten in French for what LEKA sees — changes, dependencies and incidents, never the tests themselves; the TEST-ID registry, commands and test-deletion batches dropped; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [garrytan/gstack](https://github.com/garrytan/gstack) @ `945ac30` | MIT — Copyright (c) 2026 Garry Tan | The method of gstack's `investigate/SKILL.md` (no fix without a root cause, what changed before it broke, a table of known failure patterns, recurring failures as a structural smell, three failed hypotheses and stop), into `agents/operations/debug-assistant/SKILL.md`, section « Sa méthode » | Rewritten in French for what LEKA sees — changes, dependencies and incidents, never the code or the logs; the reproduction, fix, test-run, web-search and learnings steps dropped; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` | MIT — Copyright (c) 2026 Affaan Mustafa | The method of ECC's `skills/deployment-patterns/SKILL.md` (the rollback checklist: backward-compatible migrations, progressive rollout) and `skills/production-audit/SKILL.md` (the release surface, risk lenses — security, data integrity, payments and webhooks, operations —, a verdict in bands capped by blockers, green CI is not readiness, evidence checked and missing), into `agents/development/release-analysis/SKILL.md`, section « Sa méthode » | Rewritten in French for what LEKA sees — releases, changes, services and incidents, never the code or the pipeline; the Dockerfiles, CI templates, commands and numeric score dropped; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) @ `b92f181` | MIT — Copyright (c) 2026 Affaan Mustafa | The reliability and security lists of ECC's `skills/kubernetes-patterns/SKILL.md` (several replicas for production, disruption budgets, least privilege, labels for app, version and environment, namespaces to keep tenants apart), into `agents/infrastructure/infrastructure-analysis/SKILL.md`, section « Sa méthode » | Rewritten in French at the level of the resources, accounts and environments LEKA sees, never the manifests; the YAML templates, kubectl commands and per-field settings dropped and said to be checked by the platform team; nothing copied verbatim; credited at the foot of the agent | 2026-10-13 |
