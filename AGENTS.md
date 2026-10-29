# Rules for whoever changes LEKA's code

Read by coding agents (LEKA's own code change agent, and any other) before
they change this repository. Each rule below is checked by the CI: a change
that breaks one is a red pull request. How we work as a team is in
`docs/conventions.md`.

## Web (`web/`)

- **Every word on screen comes from the dictionaries.** Visible text is never
  written into a component: it is a key of `web/lib/i18n/dictionaries.ts`,
  read with `const t = useDictionary()` then `t.section.key` (and
  `fill(t.section.key, { name })` for a value inside). Add each new key twice,
  in `fr` (French) and in `en` (English): `en` is typed by `fr`, a key missing
  from one fails `npm run typecheck`. `web/lib/i18n/hardcoded.test.ts` fails on
  any French string in `components/`, `app/`, `lib/` or `config/`.
- **Real data only.** What a screen shows (records, names, figures, statuses)
  comes from the API through the hooks of `web/lib/*-queries.ts` (TanStack
  Query), as the existing screens do. Never constants of invented records, even
  copied from a mock-up or an attached image: its sample content shows the
  look, not the data. With nothing to show, the screen says so (an empty state).
- **No em dash « — » in visible text** (dictionaries, deliverables): a colon, a
  comma, parentheses or « · » instead.
- **Tests stay green.** A component's tests sit beside it (`x.test.tsx`), the
  end-to-end ones in `web/e2e/`. Keep every `data-testid`, role, accessible
  name, link and text a test reads, or change that test in the same change, as
  strict as it was. Never delete, skip or weaken a test.
- `web/lib/api-types.ts` is generated (`npm run gen:api`): never edited by hand.
- No Prettier: format by hand like the surrounding code. ESLint must report no
  error; no `eslint-disable`, no `@ts-ignore`.
- Use only what exists: a component's props and variants, an icon of
  `lucide-react`, a route of `web/config/routes.ts`, a design token or class
  already used. A name nothing defines does not build.

## API (`api/`)

- Python 3.12, `ruff check`, `ruff format`, `mypy leka/ tests/` (strict).
- Module boundaries are a test: `api/tests/test_module_boundaries.py`. A lower
  layer never imports a higher one.
- A database change is an Alembic migration, and `alembic check` passes.
- Tests in `api/tests/`, run by `pytest` with coverage.

## What the CI runs

- api: ruff, mypy, alembic upgrade and check, pytest.
- web: `npm run lint`, `npm run typecheck`, `npm run test` (vitest, including
  the guard tests above), `npm run build`.
- e2e: Playwright against the built web and a running API.

## Commits and pull requests

Conventional Commits in English (`fix(web): …`), a pull request that says what
changes, why, and how it was tested. LEKA proposes; a person merges.
