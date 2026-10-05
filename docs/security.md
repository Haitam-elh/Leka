# Security model: authentication

What LEKA's authentication protects against, what it does not, and why each
decision was made. Written so that someone reviewing it a year from now can
tell a deliberate trade-off from an oversight.

Authorisation — what a signed-in person may do — is
[permissions.md](permissions.md). Tenant isolation is
[adr/007-tenant-isolation-strategy.md](adr/007-tenant-isolation-strategy.md).

---

## What we protect against

### Credential theft from a database leak

Passwords are hashed with **argon2id** (64 MiB, 3 passes, 2 lanes, per RFC
9106's second recommended configuration). Session tokens, verification links
and reset links are stored as SHA-256 hashes. Customers' connector
credentials are Fernet-encrypted
([adr/005](adr/005-credential-storage.md)).

A dump of our database yields no password, no usable session, and no usable
link.

**Not bcrypt**: it silently truncates at 72 bytes, so a long passphrase is
weaker than it looks. **Not a bare SHA for passwords**: designed to be fast,
which is exactly wrong.

### Account enumeration

Three forms would otherwise answer "does this person have an account here?":

| Form | What we do |
| --- | --- |
| Sign-in | One sentence — "Invalid email or password" — for an unknown address, a wrong password, and an account with no password |
| Registration | Identical response whether the address was free, and an email to the owner if it was not |
| Forgotten password | "If an account exists, a reset link is on its way", always |

**And timing counts as an answer.** When the address does not exist we still
run a real argon2 verification against a dummy hash. Without it, "no such
user" returns in microseconds and "wrong password" in ~50 ms — a difference
measurable from anywhere in the world.

### Session hijacking

- `httpOnly`, so an XSS cannot read the cookie.
- `Secure`, so it never travels in the clear.
- `SameSite=Lax` plus double-submit CSRF tokens
  ([adr/009](adr/009-cookie-strategy.md)).
- A **new** token at every sign-in — session fixation.
- Two expiry limits: 30 days absolute, 7 days idle.
- A password change revokes every other session; a reset revokes all of them.

### Brute force

Rate limiting on Redis, per IP **and** per account, because they defend
against different things: per IP stops one machine trying many accounts, per
account stops many machines trying one.

| Action | Limit |
| --- | --- |
| Sign-in | 5/min/IP and 10/hour/account |
| Registration | 3/hour/IP |
| Forgotten password | 3/hour/IP and 3/hour/address |
| Resend verification | 3/hour/account |

**No account lockout after N failures.** Locking an account means anyone who
knows an email address can deny that person access — a denial-of-service
dressed as a security control. `failed_login_count` is recorded for
observability and never used to block.

### Credentials in logs

A structlog processor masks `password`, `token`, `cookie`, `authorization`,
`secret`, `api_key` and anything ending in one of them, before any renderer
sees the line. Masking at the logging layer rather than at each call site
means the author of a future `logger.info("x", token=...)` does not need to
know the rule exists. Verified by a test that also asserts the processor is
actually installed.

Key names are not enough on their own: `logger.info("connecting",
value=...)` carries a secret under a name no list contains. A second
processor therefore masks by VALUE — every configured secret, wherever it
appears in a line, including inside a sentence, a URL or a traceback. Values
under 8 characters are left alone, or the local database password, `leka`,
would erase the product's own name from every line. Lines written by
libraries through the standard library, uvicorn and SQLAlchemy among them, do
not pass through these processors.

### A module holding a secret it has no use for

A secret rarely leaks from the module that needs it. It leaks from one that
happened to hold it. Each secret names the modules allowed to read it, and a
check parses the code on every pull request and fails, naming the file and
the line, when anything else does — including the ways a static check cannot
verify, which are refused outright. See
[adr/012](adr/012-secret-access-control.md), and `docs/configuration.md` for
the table.

### Link theft from an inbox

Verification links last 24 hours, reset links **one hour**. Both are single
use and hashed at rest. Issuing a new one kills the previous, and changing a
password kills any pending reset — a link still sitting in a forwarded email
must not undo what just happened.

---

## What we do not protect against, and accept

**Anyone who can read the application's process environment.** They have the
encryption keys and the signing key. Nothing in this design defends against
a compromised API host.

**A compromised email account.** Password recovery ends at the inbox. Someone
who controls the address can reset the password. This is the structural limit
of email-based recovery and the reason MFA exists — which is phase 4, not
this ticket.

**A stolen cookie on a machine we have no reason to distrust.** We bind
nothing to the IP or the user agent: both change legitimately (mobile
networks, browser updates) and would sign people out for no reason. The
mitigations are the idle timeout, the visible session list, and the ability
to revoke.

**Phishing.** Nothing here helps a user who types their password into a
convincing copy of our login page. WebAuthn would; it is not in this ticket.

**Targeted CSRF if the cookie ever becomes `SameSite=None`.** The
double-submit token would then be the only protection, and it deserves
re-examination at that point rather than before.

---

## Password policy, and why it looks permissive

Aligned with **NIST SP 800-63B**:

- minimum 12 characters, maximum 256, never truncated
- **no composition rules** — demanding an uppercase and a digit produces
  `Password1!` and nothing stronger
- **no forced expiry** — it produces `password2`, then `password3`
- optional check against HaveIBeenPwned using k-anonymity: only the first
  five characters of the SHA-1 hash are sent, and the password never leaves
  the process. Off by default, because a test suite must not depend on
  someone else's service being up.

The rules people expect are the ones that make passwords worse. Length is
what matters.

---

## Personal data

IP addresses are **truncated before storage** — /24 for IPv4, /48 for IPv6.
The question a session row answers is "was this roughly the same network",
not "where exactly were you". User agents are kept to 400 characters, enough
to recognise a device and not enough to fingerprint a person.

An account holds what its owner typed when registering: first and last
name and company, required; role and company size, if they chose to say.
Nothing else is asked. They are kept on `users`, shown to that person and to
whoever runs `python -m leka.identity.admin accounts` — to know who is asking
for access before granting it — and never rewritten by a later registration
with the same address, which anyone can type. Its owner changes it, signed
in, from the account menu (`PATCH /auth/me`): the only way an account made
before registration asked gets a name. The address is not changeable there —
a new one would have to be proven first. Control and formatting
characters are refused: a name travels into e-mails and into an operator's
terminal, where an escape sequence would be a stranger typing on their
screen.

Deleting a workspace cascades to everything it owns. Deleting a user cascades
to their sessions and tokens. Both are single DELETEs, which is what makes a
GDPR erasure request answerable in practice rather than in principle.

---

## How a request is authenticated, end to end

1. The browser sends the session cookie.
2. `leka.identity.wiring.load_session` hashes the token and looks up the row,
   checking revocation, absolute expiry and idle timeout. Active use refreshes
   the idle clock.
3. `get_current_user_id` — the seam LEKA-331 declared — returns the user id.
4. `get_session_store` exposes the active workspace, read from the session
   **row**, never from a header or a URL.
5. `leka.governance.get_current_principal` reads the membership **from the
   database, on this request**, and attaches the role and the workspace's
   lifecycle state.
6. The route's permission dependency decides.

Step 5 is why removing someone's membership takes effect immediately. The
role is never cached in the session: that would be the obvious optimisation
and it would turn a revocation into a delay.

**A request that lasts** — the stream of what happens to a context
(LEKA-376, [context-api.md](context-api.md) § 5) — does step 5 again at
every look, every 2 seconds: removing someone ends their stream there, as
it ends their next request. A stream lasts five minutes at most; a
reconnection is a new request, authenticated from step 1.

---

## What would change this document

MFA, SSO or WebAuthn (phase 4) each move the boundary. So does the first
customer whose security review asks for database-level isolation — see
[adr/007](adr/007-tenant-isolation-strategy.md) for the conditions under which
row-level security stops being a bad trade.
