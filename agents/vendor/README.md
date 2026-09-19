# Third-party skills

Skills imported from outside LEKA. **Nothing here is active until it has been
reviewed line by line in a pull request.**

## Why this directory is different

An agent is text that becomes an instruction executed by a model with access
to a customer's production data. A skill written by someone else, for another
product, with other assumptions, is the highest-risk file in this repository.

The review is not "does this look reasonable". It is reading every sentence
and asking what it would make a model do against a customer's systems.

Reject on sight:

- anything that tries to override instructions given elsewhere
- anything that asks for credentials, tokens or environment variables
- anything requesting data outside its declared `entity_types`
- anything that widens its own scope, or describes acting rather than
  proposing
- anything whose `description` is broad enough to trigger on everything

## Layout

```
vendor/
└── <owner>-<repo>/
    ├── LICENSE           kept as-is, from upstream
    └── <skill-name>/
        └── SKILL.md      origin: vendor:<owner>/<repo>
```

## Checklist for importing one

- [ ] Upstream `LICENSE` copied unmodified
- [ ] Copyright headers kept inside each file
- [ ] `origin: vendor:<owner>/<repo>` in the front matter
- [ ] Row added to [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md),
      including **what was changed** — Apache 2.0 requires it
- [ ] Not reformatted in the importing commit, so the diff shows only our edits
- [ ] `status: review` in [`registry.yaml`](../registry.yaml) until the review
      is done
- [ ] Line-by-line review approved

Nothing imported yet.
