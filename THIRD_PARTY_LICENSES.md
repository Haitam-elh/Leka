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
| [Simple Icons](https://simpleicons.org) @ `13.21.0` (npm `simple-icons`) | CC0-1.0 | The SVG path of twenty-six marks — GitHub, GitLab, Bitbucket, Google Cloud, Google Drive, Linear, Asana, Trello, ClickUp, Jira, Confluence, Notion, Datadog, PagerDuty, Grafana, Splunk, Kibana, PostgreSQL, MySQL, MariaDB, Oracle, Supabase, MongoDB, GraphQL, Slack, Amazon Web Services — and each brand's hex colour, into `web/components/sources/source-logo.tsx` | Paths unchanged; wrapped in one React component that colours each with its brand hex. The marks remain their owners' trademarks, used to name the system a source connects to | 2026-09-25 |
