# Data protection

LEKA-405. How LEKA protects secrets, credentials, customer data and personal
data — every path sensitive data takes, what protects it there, and what is
checked by a test so that the next table or route is held to it too.

Authentication is [security.md](security.md); who may do what,
[permissions.md](permissions.md); how long each thing is kept and how a
customer's data is erased, [data-lifecycle.md](data-lifecycle.md); tenant
isolation, [adr/007](adr/007-tenant-isolation-strategy.md).

---

## 1. What counts as sensitive

| Kind | Examples | What LEKA does with it |
| --- | --- | --- |
| **Credentials LEKA holds** | a source's token, a workspace's model key, an endpoint's signing secret | encrypted (Fernet, [adr/005](adr/005-credential-storage.md)); never returned — a hint at most |
| **Secrets found in customer data** | an AWS key pasted in Slack, a password in a Confluence page, a token in a commit | **taken out** wherever LEKA keeps text: replaced by `[redacted:<what>]` |
| **Identity numbers** | an IBAN, a card number, a French social security number | taken out, like secrets: of no use to understanding systems |
| **Personal data** | names, e-mail addresses, phone numbers | kept — who owns and who answers is what the company model is about — counted, erased with the workspace or the record ([data-lifecycle.md](data-lifecycle.md)) |
| **LEKA's own secrets** | database password, encryption keys, S3 credentials | environment only; each readable by the modules that need it ([adr/012](adr/012-secret-access-control.md)); their age watched |

## 2. The detector

One for all of LEKA: `api/leka/core/sensitive.py`, pure.

- **Secrets** by their shape:
  - vendors' tokens (AWS, GitHub, GitLab, Atlassian, Slack, Google, OpenAI and Anthropic, Stripe, Linear, Notion, npm, PyPI, Hugging Face, Docker, SendGrid, JWTs, Azure account keys);
  - private keys;
  - a password in a URL (`postgres://user:it@host`);
  - a password said in a setting, in English or French: `password: "…"`, `DB_PASSWORD=…`, « mot de passe : … », `mdp=…`.
- **What only names a secret is not one**: `${DB_PASSWORD}`, `<password>`, `password: user_password`, `api_key = settings.api_key`.
- **Identity numbers only when their issuer's check says so**:
  - a card passes Luhn and starts like a network's card (so a millisecond timestamp is not one);
  - an IBAN passes mod 97;
  - a NIR has its key.
- **What it gives back**: kinds, counts and positions — never a value outside the text it was found in.
- **Versioned** (`SENSITIVE_VERSION`): a newer detector scans again what an older one scanned.

It is a detector, not a guarantee: a secret in a shape no rule knows passes. The rules are in one place so that adding one protects every path at once.

## 3. Every path sensitive data takes

| Path | Where it rests | What protects it |
| --- | --- | --- |
| A source's credentials | `source_credentials.ciphertext` | Fernet; a hint and a rotation date in the API; re-encrypted by a key rotation (`scripts/rotate_encryption_key.py`) |
| A workspace's own model key (LEKA-429) | `workspace_models.key_ciphertext` | the same |
| An action endpoint's signing secret (LEKA-391) | `action_endpoints.secret_ciphertext` | the same; shown once, at creation |
| Passwords, sessions, e-mail links | `users.password_hash`, `*.token_hash` | argon2id; SHA-256 ([security.md](security.md)) |
| A vendor's payload as collected | the object store, `{workspace}/{source}/…` | encrypted on write (§ 5); under its workspace's prefix; expires by its source's retention — **or `found_payload_days` (7) after a secret or an identity number was found in it** (§ 7) |
| A webhook's body | `webhook_deliveries.body` | seconds, until a pass stores it as a payload |
| What extraction made of a record | `extracted_records.result` | **protected before it is kept**: secrets and identity numbers replaced; `sensitivity` says what was found — kinds and counts |
| Everything built from it | parsed and normalised records, the company model, the search index, contexts, every prompt | read from the protected record: no copy of what was taken out is made downstream |
| An intention, as typed | `intentions.text`, `title` | guarded when asked and asked again: a secret or an identity number typed in it is taken out before it is kept or read by a model |
| A vendor's error | sync diagnostics, connector errors | cleaned of the source's own secrets and of every shape the detector knows |
| Logs | stdout | masked by key name and by every configured secret's value ([security.md](security.md)) |
| A model's answer | — | LEKA-406's output checks: secrets and personal data redacted, blocked or flagged — to share this detector once merged |

Nothing returns a credential: `tests/test_data_protection_structure.py` walks every response the API can give and fails on a field named like a secret that is not listed with why — a secret shown once, the CSRF token, a hint.

## 4. In transit

| Between | How |
| --- | --- |
| A browser and LEKA | TLS at the proxy (Caddy, certificates renewed on their own), HSTS for a year, `Secure` session cookie (`deploy/Caddyfile`, [adr/009](adr/009-cookie-strategy.md)) |
| LEKA and PostgreSQL (RDS) | TLS (`?ssl=require`). Production refuses to start with a URL that turns it off; the connection's TLS is read from PostgreSQL itself (`pg_stat_ssl`) and shown to administrators (§ 8) |
| LEKA and S3 | HTTPS (the SDK's default) |
| LEKA and a customer's systems | connectors over HTTPS to public addresses only (`PublicTransport`); database connectors over TLS where the engine offers it |
| LEKA and a model | HTTPS in production (LEKA-429's guard) |
| LEKA and Redis | the same host, on the containers' private network — never across one |

## 5. At rest

- **Credentials and secrets**: Fernet, MultiFernet for rotation; a test fails if a ciphertext column appears that the rotation does not rewrite (`tests/test_key_rotation.py`).
- **The object store**: every write asks Amazon S3 to encrypt — `AES256` by default, `aws:kms` when `LEKA_S3_SERVER_SIDE_ENCRYPTION` says so. Production refuses `none` on Amazon S3. On another endpoint (MinIO, R2), nothing is asked unless configured: R2 encrypts on its own, MinIO refuses the header without a key service.
- **The database**: RDS storage encryption is AWS's, configured with the instance. It is not visible from the application and is checked in the AWS console.
- **No secret in a column**: a test fails on a column named like a secret that is not a hash, a ciphertext, a count or a date, and on a binary column that is not a ciphertext but for those listed with why.

## 6. Tenant isolation

[adr/007](adr/007-tenant-isolation-strategy.md):
1. composite keys that make a cross-tenant row impossible;
2. repositories built for one workspace;
3. a session guard that scopes or refuses every ORM statement, failing closed;
4. the request's workspace taken from its session.

Raw SQL in the application reads no customer table. Objects are kept under their workspace's prefix and erased with it. `tests/test_tenant_isolation.py` checks the structure and calls every route as another workspace.

## 7. Retention of protected data

| What | Kept |
| --- | --- |
| A raw payload | its source kind's days (30–90), or less if the source says so ([data-lifecycle.md](data-lifecycle.md)) |
| A raw payload a secret or an identity number was found in | **at most `found_payload_days` from then** (7 by default, 1 to 30) — never longer than the line above |
| An extracted record | as long as its record is live — protected |
| An intention | with its workspace — guarded |

`found_payload_days` is the workspace's data protection policy (`PUT /governance/data-protection/policy`, `policy:manage`). A change applies to what is found next; each change is kept in the governance trail, before and after (`governance_events`, `subject_type` protection).

A batch whose payload went early is not extracted again by a newer extractor: its records keep their protected extraction until the vendor's object changes and is collected anew.

**The sweep** (`data-protection-sweep`, every 15 minutes, [background.md](background.md)) protects what was extracted before, or under an older detector:
- it works in place, 1,000 records per workspace per pass;
- it shortens their originals' retention the same way.

## 8. Who sees what, and what is kept of it

| | Permission |
| --- | --- |
| The platform's protections, the policy, what was found per source (`GET /governance/data-protection`) | `access:read` |
| The policy changed | `policy:manage` |

Both are decided and kept as every permission is ([permissions.md](permissions.md), the access trail). What was found is said in kinds and counts — « clé AWS × 1 », « e-mail × 40 » — never a value. An entity an administrator restricts is hidden from those who may not read it (LEKA-402).

**In the app**, Sécurité & gouvernance › Données shows:
- the platform's protections as read from the running process:
  - the database connection's TLS;
  - how files are encrypted;
  - the credentials' keys;
  - the isolation;
  - the session cookie;
  - the secrets overdue for rotation;
- per source, what was found and masked;
- the policy.

## 9. Tested

| Test | What it checks |
| --- | --- |
| `tests/test_sensitive.py` (pure) | each secret by its shape, taken out; what only names one, left; a quoted value always one; French wording; personal data counted, identity numbers taken out only when their check passes; a record protected through and through; a vendor's error cleaned |
| `tests/test_data_protection.py` | a record protected before it is kept, nothing extracted still holding the secret; its original kept 7 days, or the workspace's choice, one with nothing in it keeping its retention; the sweep, once; the API: an auditor's, the policy a manager's, refused out of range, kept in the trail once |
| `tests/test_data_protection_intentions.py` | an intention asked, and asked again, with a password or a card keeps neither |
| `tests/test_data_protection_structure.py` | no secret in a column, no secret in a response, production refusing plaintext |
| `web/components/governance/data-protection.test.tsx` | the tab |
| `e2e/data-protection.spec.ts` | the tab, in a browser, on the demo: the protections, the policy changed and set back |

## Not yet

- **Webhook bodies encrypted**: kept seconds today; encrypting them would need them in the key rotation.
- **A key per customer (BYOK, KMS)**: one platform key encrypts every workspace's credentials today.
- **Attachments and images**: the detector reads text; a secret in a screenshot passes.
- **A workspace's own patterns**: the rules are LEKA's, the same for every workspace.
- **LEKA-406 on this detector**: its output checks keep their own patterns until it merges, then import `core.sensitive`.
