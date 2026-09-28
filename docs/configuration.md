# Configuration

Every knob the backend reads, where its value comes from, and — for the
secrets — who may read it and how often it is rotated.

The fields live in `api/leka/core/settings/`, one file per domain, assembled
into one `Settings` in `api/leka/core/config.py`. The environment is read
**once, at import**: an incomplete environment stops the process on startup
rather than surfacing three weeks later as a `None` in production. The
message names every missing or invalid variable at once:

```
LEKA cannot start: its environment is incomplete or invalid.

  LEKA_DATABASE_URL: Field required
  LEKA_ENCRYPTION_KEYS: Field required

Copy .env.example to .env and fill it in — see docs/setup.md.
```

**A blank value is not a value.** `.env.example` ships optional variables
present but empty, so a copied `.env` yields `""` rather than an absent
variable. Blank is read as "not configured" (`core/settings/_blank.py`).
Production once started with a bucket named `""` because that was not true.

## Where values come from

| Environment | Source |
| --- | --- |
| local | `.env`, copied from `.env.example` — see `docs/setup.md` |
| CI | the `env:` block of `.github/workflows/ci.yml`: the four required variables with throwaway values, committed on purpose, plus `LEKA_ENVIRONMENT=ci` |
| staging, production | **nothing yet.** No host is chosen, nothing is deployed, and no real secret exists anywhere. When one does, it belongs in that host's secret store, never in Git — see `docs/adr/012-secret-access-control.md` for when an external secret manager becomes worth it |

## Runtime

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_ENVIRONMENT` | `local` | `local`, `ci`, `staging` or `production`. Production turns on the startup guards and stops publishing `/docs`; staging and production warn about old secrets |
| `LEKA_DEBUG` | `false` | Debug behaviour. Never true in production |
| `LEKA_API_V1_PREFIX` | `/api/v1` | Where the API is mounted |
| `LEKA_WEB_URL` | `http://localhost:3000` | Public address of the web app, no trailing slash. Every link in an email is built on it. In staging and production it must be `https://` and not localhost, or the API refuses to start |
| `LEKA_CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list of origins a browser may call the API from |
| `LEKA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `LEKA_LOG_FORMAT` | `console` | `console` for a terminal, `json` for a log collector |
| `LEKA_AGENTS_DIR` | `<repo>/agents` | Where the agent markdown files live |

## Database and queue

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_DATABASE_URL` | **required** | `postgresql+asyncpg://…`. Any other driver is refused at startup, where the error names the variable |
| `LEKA_REDIS_URL` | **required** | Queue backend and rate-limit counters |
| `LEKA_DB_POOL_SIZE` | `5` | Pooled connections, 1–100. Small by default: two laptops |
| `LEKA_DB_MAX_OVERFLOW` | `10` | Extra connections under load, 0–100 |
| `LEKA_DB_ECHO` | `false` | Log every SQL statement. Useful for an afternoon |

## Security

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_SECRET_KEY` | **required** | Root of every signature the server hands a client. `leka.core.signing` derives a key per purpose from it |
| `LEKA_ENCRYPTION_KEYS` | **required** | JSON list of Fernet keys for customers' credentials at rest. The FIRST encrypts, all are tried when decrypting — which is what makes rotation possible without downtime |
| `LEKA_SECRETS_ROTATED_ON` | `{}` | JSON object: when each secret was last rotated **in this environment**, e.g. `{"secret_key": "2026-09-22"}`. An unknown name or a future date stops startup |
| `LEKA_SESSION_ABSOLUTE_LIFETIME_DAYS` | `30` | A session dies after this whatever happens, 1–365 |
| `LEKA_SESSION_IDLE_LIFETIME_DAYS` | `7` | …and after this unused, 1–90 |
| `LEKA_VERIFICATION_TOKEN_LIFETIME_HOURS` | `24` | Account verification link, 1–168 |
| `LEKA_RESET_TOKEN_LIFETIME_HOURS` | `1` | Password reset link, 1–24. Short on purpose: it waits in an inbox, and whoever reads that inbox owns the account for as long as it lives (OWASP Forgot Password Cheat Sheet). Raise it only for a documented reason |
| `LEKA_SESSION_COOKIE_NAME` | `leka_session` | |
| `LEKA_SESSION_COOKIE_SECURE` | `true` | HTTPS only. `false` is for local development and is refused in production |
| `LEKA_SESSION_COOKIE_SAMESITE` | `lax` | `lax`, `strict` or `none`; `none` is refused in production — see `docs/adr/009-cookie-strategy.md` |
| `LEKA_CHECK_PASSWORDS_AGAINST_BREACHES` | `false` | Check new passwords against HaveIBeenPwned by k-anonymity. Off by default: it is a network call |

## E-mail

With nothing configured, verification and recovery links are written to the
log. That is what makes those flows testable without an account anywhere —
and why **staging and production refuse to start without SMTP or Resend**:
online, a log nobody reads is an email nobody receives.

Emails leave after the response, so after the request's commit: a link never
names a token the database did not keep. To test the configured sender by
hand, errors in the open:

```bash
python -m leka.identity.email --test someone@example.com
```

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_EMAIL_FROM` | `LEKA <no-reply@leka.example>` | With OVH this MUST be the authenticated mailbox, or OVH drops the mail silently. When SMTP is configured, an address different from `LEKA_SMTP_USERNAME` stops startup |
| `LEKA_SMTP_HOST` | — | SMTP is used when the host and the password are both set |
| `LEKA_SMTP_PORT` | `465` | |
| `LEKA_SMTP_USERNAME` | — | The full address, with OVH |
| `LEKA_SMTP_PASSWORD` | — | |
| `LEKA_SMTP_USE_SSL` | `true` | `true` for port 465, `false` for 587 (STARTTLS) |
| `LEKA_RESEND_API_KEY` | — | API sender, used when SMTP is not configured |
| `LEKA_EMAIL_OUTBOX_FILE` | — | Local and CI only: the console sender also appends each message, as one JSON line, to this file. The browser tests read their links from it. Refused in staging and production |

## Model access

Read by `leka.capabilities` and nowhere else (architecture rule 7). Both keys
may be absent: the platform boots and serves without a model.

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_LLM_PROVIDER` | `mistral` | `mistral` or `anthropic`. Mistral is the default so the European path is the one exercised every day |
| `LEKA_ANTHROPIC_API_KEY` | — | |
| `LEKA_MISTRAL_API_KEY` | — | |

## Object storage and retention

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_OBJECT_STORE` | `local` | `local` or `s3`. `local` is refused in production: a container's disk is not durable storage |
| `LEKA_OBJECT_STORE_PATH` | `var/objects` | Relative paths resolve against the repository root |
| `LEKA_S3_BUCKET` | — | Required when the store is `s3`, checked at startup |
| `LEKA_S3_ENDPOINT_URL` | — | R2, S3 or MinIO: the same code, only this changes |
| `LEKA_S3_REGION` | `auto` | R2 wants `auto`; S3 wants a real region |
| `LEKA_S3_ACCESS_KEY_ID` | — | An identifier, not a secret — but it names the account the secret below belongs to |
| `LEKA_S3_SECRET_ACCESS_KEY` | — | |
| `LEKA_MAX_OBJECT_BYTES` | `1073741824` | Largest payload stored, in bytes. A ceiling, not a target |
| `LEKA_RAW_PAYLOAD_RETENTION_DAYS` | `{}` | JSON object overriding retention per source kind, in DAYS, 1–3650. The policy itself is in `leka/ingestion/retention.py` |

## Background loop

See docs/background.md for how the loop as a whole is run and operated;
this is only what each variable is for. `leka/core/settings/background.py`.

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_DISPATCH_BATCH_SIZE` | `100` | Events turned into runs, and runs offered to Redis, per pass, 1–1000 |
| `LEKA_DISPATCH_MAX_ATTEMPTS` | `5` | An event that keeps failing to dispatch is given up on after this many passes, 1–50 |
| `LEKA_EVENT_RETENTION_DAYS` | `14` | Settled events (runs created or failed) are kept this long, 1–365. A pending one is never pruned |
| `LEKA_JOB_MAX_ATTEMPTS` | `3` | A job run is failed for good after this many attempts, 1–20 |
| `LEKA_JOB_RETRY_BASE_SECONDS` | `30` | Delay before the first retry; doubles each attempt up to the cap below, 1–3600 |
| `LEKA_JOB_RETRY_MAX_SECONDS` | `3600` | Cap on the retry delay, 1–86400. Refused at startup if below the base |
| `LEKA_JOB_LEASE_SECONDS` | `300` | A worker silent this long (30–7200) is taken to be dead; it renews at a third of this |
| `LEKA_JOB_STALE_ENQUEUED_SECONDS` | `3600` | A run the queue never picked up (60–86400) is offered again |
| `LEKA_RECONCILE_DELETES` | `false` | Whether the scheduled orphan sweep may DELETE. Off means it only reports |

## Monitoring

Errors, and nothing else. No metrics backend and no dashboard: the SQL in
docs/background.md is the dashboard, by decision, and a second vendor to
configure, pay and audit buys nothing on a product with no traffic yet.
`leka/core/settings/monitoring.py`, wired up in `leka/platform/monitoring.py`.

| Variable | Default | What it does |
| --- | --- | --- |
| `LEKA_SENTRY_DSN` | — | The Sentry project. Empty means monitoring is off, which is the default everywhere but staging and production |
| `LEKA_SENTRY_TRACES_SAMPLE_RATE` | `0.0` | Performance tracing, 0.0–1.0. Off: it is billed per span and nobody reads it yet |
| `LEKA_SENTRY_SEND_DEFAULT_PII` | `false` | Typed so it cannot be turned on. PII here means a customer's e-mail address on a third party's servers |
| `LEKA_RELEASE` | — | The commit sha this container was built from. Set by the deployment pipeline; it is what makes an error name the commit that caused it |

Events are scrubbed before they leave, with the same masker that protects the
logs — see `leka.core.logging.scrub_secrets` and
`tests/test_monitoring.py`. Sentry sends the local variables of every frame
in a traceback, and `settings` is a local variable in more places than anyone
can enumerate.

## The secrets: who reads them, how often they rotate

Nothing else may read these. The rule is enforced on every pull request by
`api/tests/test_secret_access.py`, which parses the code and fails naming the
file and the line — see `docs/adr/012-secret-access-control.md`. The
lifetimes are declared next to each field, with `RotateEvery`; the procedures
are in `docs/runbook.md`.

| Variable | Read only by | Rotate every |
| --- | --- | --- |
| `LEKA_SECRET_KEY` | `leka.core.signing` | 365 days |
| `LEKA_ENCRYPTION_KEYS` | `leka.platform.secrets` | 365 days |
| `LEKA_DATABASE_URL` | `leka.db.session`, `alembic.env`, `leka.background.runner` | 365 days |
| `LEKA_REDIS_URL` | `leka.core.ratelimit`, `leka.platform.health`, `leka.background.jobs` | 365 days |
| `LEKA_SMTP_PASSWORD` | `leka.identity.email` | 365 days |
| `LEKA_RESEND_API_KEY` | `leka.identity.email` | 90 days |
| `LEKA_ANTHROPIC_API_KEY` | `leka.capabilities` | 90 days |
| `LEKA_MISTRAL_API_KEY` | `leka.capabilities` | 90 days |
| `LEKA_S3_SECRET_ACCESS_KEY` | `leka.platform.storage` | 90 days |
| `LEKA_SENTRY_DSN` | `leka.platform.monitoring` | 365 days |

A connection URL counts as a secret because it carries a password. 90 days
for keys another company issued and sees used — that is AWS's own figure for
access keys; 365 for what only we hold.

Two exceptions, neither of them a variable. `settings.llm_api_key` returns
whichever model key the selected provider uses, and belongs to
`leka.capabilities` like the keys themselves. `settings.secret_values`
returns every configured secret at once and belongs to `leka.core.logging`:
recognising secrets in a log line is exactly that module's job, and nobody
else's.

**Logs.** Secrets are masked twice: by key name (`password=`, `token=`,
`api_key=`) and by value, anywhere in a line — including inside a sentence, a
URL or a traceback. Values shorter than 8 characters are not masked, or the
local database password, `leka`, would erase the product's own name from
every line. Lines written by libraries through the standard library —
uvicorn, SQLAlchemy — do not pass through structlog's processors and are not
masked.

## Read by the tests and CI, never by the application

| Variable | What it does |
| --- | --- |
| `LEKA_REQUIRE_S3_TESTS` | `1` turns a skipped S3 test into a failure. CI sets it, so the adapter is never reported as verified by a test that did not run |
| `LEKA_S3_TEST_TARGET` | `minio` (default) or `aws`, to point the S3 suite at the real validation bucket |
| `LEKA_S3_TEST_ENDPOINT` | Where that suite finds its server |
| `LEKA_S3_TEST_ACCESS_KEY` | |
| `LEKA_S3_TEST_SECRET_KEY` | |
| `LEKA_REQUIRE_MYSQL_TESTS` | `1` turns a skipped MySQL connector test into a failure. CI sets it |
| `LEKA_MYSQL_TEST_URL` | The MySQL those tests connect to as an admin: `mysql://root:leka@127.0.0.1:3306` by default, `docker compose up -d mysql` |
| `LEKA_REQUIRE_MARIADB_TESTS` | The same for the MariaDB connector's tests |
| `LEKA_MARIADB_TEST_URL` | The MariaDB they connect to as an admin: `mysql://root:leka@127.0.0.1:3307` by default, `docker compose up -d mariadb` |
| `LEKA_REQUIRE_SQLSERVER_TESTS` | The same for the SQL Server connector's tests |
| `LEKA_SQLSERVER_TEST_URL` | The SQL Server they connect to as an admin: `mssql://sa:Leka-local-1@127.0.0.1:1433` by default, `docker compose up -d sqlserver` |
| `LEKA_REQUIRE_ORACLE_TESTS` | The same for the Oracle connector's tests |
| `LEKA_ORACLE_TEST_URL` | The Oracle they connect to as an admin, over plain TCP: `oracle://system:Leka-local-1@127.0.0.1:1521/FREEPDB1` by default, `docker compose up -d oracle`. The connector's own sessions use TCPS on 2484 |
| `LEKA_REQUIRE_MONGODB_TESTS` | The same for the MongoDB connector's tests |
| `LEKA_MONGODB_TEST_URL` | The MongoDB they connect to as an admin: `mongodb://root:leka@127.0.0.1:27017` by default, `docker compose up -d mongodb` |
| `LEKA_PYTHON` | The interpreter Playwright starts the API with |

## Adding a setting

1. Write it in `api/leka/core/settings/<domain>.py`, or create that file and
   add two lines to `core/config.py` — an import and a name in the base list.
2. Add a row to this document. `tests/test_config.py` fails otherwise, and
   fails again if this document names a variable that no longer exists.
3. Give it a comment in `.env.example`.

If it holds a secret, three more:

4. Type it `SecretStr`, so it cannot be printed by accident, and so the
   checks below can find it.
5. Declare its lifetime on the field: `Annotated[SecretStr, RotateEvery(days=90)]`.
6. Name its owners in `SECRET_OWNERS` (`tests/test_secret_access.py`) and in
   the table above. Both are checked; neither can fall behind in silence.
