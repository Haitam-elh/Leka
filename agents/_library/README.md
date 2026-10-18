# Method libraries

What an agent works by, too long to be its instructions: guides it reads
while it runs, one file at a time, with the `read_method` tool. **A library
is never an agent.** The loader skips every directory whose name starts
with `_` (this one, `_template/`), so a `SKILL.md` here is never registered,
routed or run on its own.

An agent opens a library by naming it in its front matter:

```yaml
method: _library/design
tools: [..., read_method]
```

`read_method` without a path gives the library's index (each file, what it
is for); with a path, that file's text. Only `.md` files under the library
named, nothing else under `agents/`, nothing outside it.

## Why it is reviewed like code

What an agent reads with `read_method` reaches the model as its method —
text a model follows, with access to a customer's data. So a library is
reviewed line by line in the pull request that changes it, and every agent
that reads it gets a new version. The runtime's rules still come first: a
guide teaches an agent how to judge, never what it may do — no file
written, no command run, nothing claimed seen. And a deliverable never
names a guide, its path or where a method comes from: it speaks as LEKA.

## What is here

| Library | What it is | Read by |
| --- | --- | --- |
| `design/` | LEKA's design guides, written in French for LEKA's runtime: the principles of a review, animations, the motion audit, where to animate, building an animation, its performance, the worst case, the phone, fluid interfaces, React Native, libraries, notifications, design directions, the vocabulary of motion, Swift — and its index, `README.md` | `design-review` (every guide), `motion-review`, `ui-quality-review`, `code-change` (an interface's change) |

Provenance and licences: [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).

To change a guide: edit it, keep its `titre` and `description` front matter
(the index reads them), bump the version of every agent that reads it, and
keep the tests that pin what each agent loads in step.
