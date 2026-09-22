# ADR 012 — Secret access control: a check in CI, not an accessor at runtime

**Status:** accepted
**Date:** 2026-09-22
**Ticket:** LEKA-335

## Context

`from leka.core.config import settings` gives a module every secret the
platform holds. Seventeen modules import it; five have any business holding a
secret. Nothing said which was which, and nothing noticed when that changed.

LEKA-335 asks that "services can access only the credentials they are
authorized to use". The threat this answers is not an attacker inside the
process — anyone who can run code in it can read the environment anyway. It
is the ordinary way secrets actually leak: a log line, a traceback, a debug
endpoint, an error report written by a module that had no reason to be
holding the value in the first place.

There was already one real instance. `leka.db.pagination` read
`LEKA_SECRET_KEY` to sign pagination cursors — the same key that will sign
everything else the server ever hands a client, held by the module least
likely to need it.

## Decision

**Ownership is declared, and a static check enforces it on every pull
request.**

1. `SECRET_OWNERS` in `api/tests/test_secret_access.py` names, for each
   secret, the modules allowed to read it. `docs/configuration.md` carries
   the same table for people; a test compares the two.
2. The check parses the source of `leka/`, `alembic/` and `scripts/` and
   fails, naming the file and the line, on any other read. A read is
   recognised by the attribute NAME, whatever object it is read from, so a
   renamed import or an alias changes nothing.
3. **What cannot be checked is refused**: `getattr` with a computed name,
   `vars(settings)`, `model_dump()`, aliasing the settings object, a star
   import, or a `LEKA_*` secret read straight from `os.environ`. A read this
   check cannot see is a read it would have to take on trust.
4. The table cannot fall behind. Secrets are found from the types —
   `SecretStr`, a tuple of them, a property returning one, a URL able to
   carry a password — so a new one fails CI until it has an owner. A field
   *named* like a secret but typed `str` fails too, as does an owner that
   does not exist and a grant nothing uses.

Two consequences in the code, from applying it:

- `leka.core.signing` is now the only module that reads `LEKA_SECRET_KEY`.
  Everything else asks it for a signature under a named purpose, and each
  purpose signs with its own key, derived from the root by HMAC. A cursor
  signature proves nothing anywhere else, and `leka.db.pagination` holds no
  key material at all.
- `leka.core.logging` reads every configured value, deliberately: masking
  secrets in log lines requires recognising them, which requires holding
  them. It is the one module whose job that is.

## Why not an accessor at runtime

The alternative considered was `get_secret("s3_secret_access_key")`, refusing
callers by module name, or a per-module settings object handed out at
construction.

- **It fails in the wrong place.** A runtime refusal fires in production, on
  whichever path first exercises it — often an error path, which is exactly
  where a secret gets logged. The static check fires in CI, on the pull
  request that introduced the read.
- **It is not stronger.** An accessor keyed on the caller's `__name__` is
  spoofable in one line. Neither approach defends against code that wants to
  cheat; both catch mistakes, and mistakes are what leak secrets.
- **It costs a refactor of seventeen modules** and changes signatures that
  have nothing to do with secrets, for a team of two working part-time.
- **It costs something on every call**, where the static check costs nothing
  at runtime.

## What this does not do

- It is **not a security boundary**. Any module can import `os` and read the
  environment; the check flags the obvious spelling of that and no more.
- **Tests are not scanned.** They are not services, and the values they hold
  are fakes.
- **Library log lines are not masked by value.** uvicorn and SQLAlchemy log
  through the standard library, which does not pass through structlog's
  processors.

## What would change our mind

- **A second deployable with a different set of secrets** — a worker that
  must not hold what the API holds. Rules per module would then be the wrong
  unit; per process is.
- **A credential that has to be looked up dynamically**, per connector or per
  customer. Those are already rows in `sources.credentials_encrypted`, not
  settings, but if one ever became a setting the check could not see the read
  and an explicit accessor would be the honest answer.
- **A third party auditing secret access**, which needs a record of who read
  what and when — a runtime concern that no static check can produce.

## Phase 3: an external secret manager

Not now, and not because it would not help: because nothing is deployed, no
host is chosen, and no real secret exists anywhere yet. AWS Secrets Manager
or Vault becomes worth its cost at the first of:

- a production deployment holding a customer's credentials;
- a customer requiring bring-your-own-key, or an audit trail of secret access;
- a third environment to keep in step by hand.

It changes where values come from, not this decision. Settings stay the
interface — values arrive as environment variables, or through a settings
source that fetches them — so the ownership check and the log masking survive
the change untouched.
