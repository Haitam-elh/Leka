# LEKA

LEKA connects to a company's information system (GitHub, Jira, Confluence, AWS,
Datadog, Slack), continuously maintains an up-to-date map of its architecture,
and answers operational questions with evidence.

The expensive work happens in the background, continuously — not when the user
asks. Two loops:

- **background loop** (worker): source sync → normalization → graph
- **interactive loop** (API): intention → already-prepared context → analysis → answer

## Layout

| Path      | What lives there                                  |
| --------- | ------------------------------------------------- |
| `api/`    | Python 3.12 / FastAPI backend (modular monolith)   |
| `web/`    | Next.js 15 frontend                               |
| `agents/` | LEKA agents — markdown files, not code            |
| `docs/`   | Architecture, ADRs, setup, conventions            |

## Getting started

See [docs/setup.md](docs/setup.md) — from clone to first run.

## Contributing

See [docs/conventions.md](docs/conventions.md) — branches, commits, pull
requests, and the architecture rules every change is held to.
