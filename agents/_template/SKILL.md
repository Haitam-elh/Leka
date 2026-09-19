---
name: REPLACE_ME
description: Use when <the situation that should trigger this agent>. One sentence. This field decides whether the agent runs at all.
version: 0.1.0
entity_types: [service]
requires: []
mode: read_only
risk: low
outputs: finding
origin: internal
---

# <Agent name>

<!-- `name: REPLACE_ME` is invalid on purpose: it is not
kebab-case, so the loader refuses this file. Copying the template and
forgetting to fill it in fails loudly instead of registering an agent
called REPLACE_ME. -->

## When this runs

<The situation, in a sentence or two. Expand on `description`, do not repeat
it verbatim.>

## What it looks at

<Which entities and relationships. Be specific — an agent that asks for
everything gets a context window of noise.>

## What it produces

<The shape of the finding, and what evidence it must cite. A finding with no
citation is a guess.>

## What it must not do

<Boundaries. At minimum: read-only, no action without approval.>
