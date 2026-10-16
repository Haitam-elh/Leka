# Method libraries

What an agent works by, too long to be its instructions: guides it reads
while it runs, one file at a time, with the `read_method` tool. **A library
is never an agent.** The loader skips every directory whose name starts
with `_` (this one, `_template/`), so a `SKILL.md` here is never registered,
routed or run on its own.

An agent opens a library by naming it in its front matter:

```yaml
method: _library/emilkowalski-skills
tools: [..., read_method]
```

`read_method` without a path gives the library's index (each file, what it
is for); with a path, that file's text. Only `.md` files under the library
named, nothing else under `agents/`, nothing outside it.

## Why it is reviewed like `vendor/`

What an agent reads with `read_method` reaches the model as its method —
text a model follows, with access to a customer's data. So a library from
outside LEKA is held to `vendor/README.md`: imported unmodified, its licence
kept beside it, every file read line by line in the pull request that brings
it, and recorded in [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).
The runtime's rules still come first: an agent's own instructions say which
of a guide's steps do not apply here (writing files, running commands,
opening a browser) — a guide teaches it how to judge, never what it may do.

## What is here

| Library | Source | Licence | Read by |
| --- | --- | --- | --- |
| `emilkowalski-skills/` | [emilkowalski/skills](https://github.com/emilkowalski/skills) @ `2d22863` (2026-10-11), unmodified: its 15 skills with their references, `README.md`, `performance-cheatsheet.md`, `LICENSE` | MIT — © 2026 Emil Kowalski | `design-review` (every guide), `motion-review`, `ui-quality-review`, `code-change` (an interface's change) |

To update one: copy the new upstream commit over it unmodified, read the
diff line by line, bump the version of every agent that reads it, and
update the row above and `THIRD_PARTY_LICENSES.md`.
