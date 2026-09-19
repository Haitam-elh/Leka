# ADR 004 — Agents are markdown files, not Python classes

**Status:** accepted · **Date:** 2026-09-19 · **Ticket:** LEKA-329

## Context

Around LEKA's core sit dozens of specialised agents: correlate an incident
with a deployment, detect configuration drift, spot an undocumented
dependency, map service ownership. The list is open-ended and grows with what
customers ask for.

Most of what an agent *is* turns out to be prose: when it should trigger, what
it should look at, what it should conclude, what it must not do. The code
underneath — fetch a subgraph, call a model, return a finding — is nearly
identical from one agent to the next.

So the question is what an agent is made of, and who can write one.

## Decision

**An agent is a markdown file with YAML front matter**, following the Agent
Skills pattern from the Claude ecosystem.

```
agents/
├── README.md              the format, the rules, how to add one
├── registry.yaml          index: path, version, status
├── _template/SKILL.md     the file you copy
├── incident/              incident analysis
├── drift/                 drift detection
├── codebase/              repository analysis
└── vendor/                third-party skills — reviewed line by line
```

Mandatory front matter:

| Field | Meaning |
| --- | --- |
| `name` | unique identifier, kebab-case |
| `description` | one sentence: **when** to use this agent |
| `version` | semver |
| `entity_types` | what it operates on |
| `requires` | connectors that must be connected |
| `mode` | `read_only` or `proposes_action` |
| `risk` | `low`, `medium`, `high` |
| `outputs` | the kind of finding it produces |
| `origin` | `internal` or `vendor:<repo>` |

`description` is the most important field: it is what decides whether the
agent triggers at all. A vague description produces an agent that either never
runs or runs constantly.

**`agents/` is content. `capabilities/` is the loader that reads, validates
and registers it.** They never mix.

## Alternatives rejected

**A Python class per agent.**
The obvious choice, and it puts a compiler between us and a typo. But it makes
adding an agent a code change, a pull request, a deploy — for what is, in
substance, a paragraph of English. It also puts the interesting part, the
prompt, inside a string literal where it is awkward to read and awkward to
diff. Reviewing "does this agent do the right thing" means reading a `.py`
file for the one triple-quoted block that matters.

**Agents in the database, edited through an admin UI.**
Genuinely tempting: no deploy at all, and non-engineers can contribute. It
also loses Git — no diff, no review, no blame, no revert. Given that an agent
is text that becomes an instruction executed by a model with access to a
customer's **production data**, "who changed this and when" is not a nice-to-
have. A row in a table is editable by anyone with database access and leaves
no trace.

**A general orchestration framework (LangChain and similar).**
Solves problems we do not have yet, at the cost of a dependency that moves
faster than we can follow, and abstractions we would have to learn before we
could debug them. `capabilities` is a few hundred lines we control.

**A DSL for agents.**
Every DSL becomes a programming language eventually, and then you own a
compiler. Markdown plus a validated YAML header is the smallest thing that
works.

## Consequences

**Good.** Agents are versioned in Git, reviewed in pull requests, reverted
like anything else. Adding one requires no redeployment. The interesting part
— the prose — is the file, not a string inside a file. Product people can
write and review agents. Importing a third-party skill is copying a file.

**Bad.** Errors surface at load time, not compile time, which puts the weight
on `capabilities/schemas.py` doing strict validation and failing loudly.
There is no type checking across agents. Dozens of markdown files need a
registry to stay navigable — hence `registry.yaml`.

**The real risk is security, and it is not a side note.** A markdown file that
becomes an instruction executed by a model with production access is an
injection surface. Hence, without exception:

1. Anything in `vendor/` is reviewed **line by line** in a pull request before
   it is activated.
2. Agents run **read-only**.
3. An agent in `proposes_action` mode proposes. It never executes. Execution
   goes through `intentions`, after explicit, named, timestamped human
   approval.

**Watch for:** agents growing conditional logic that wants to be code; a
`description` field so broad the agent triggers on everything; vendor skills
imported faster than they can be reviewed properly.
