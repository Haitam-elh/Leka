# ADR 009 — Host-only session cookie, SameSite=Lax, and a parent-domain requirement

**Status:** accepted · **Date:** 2026-09-20 · **Ticket:** LEKA-330

## Context

The session token travels in a cookie. Every attribute on that cookie is a
security decision, and none of them fails loudly when it is wrong: the
application works perfectly and quietly stops protecting anyone.

There is also a deployment fact to reckon with. The frontend is planned for
Vercel and the API for Railway. If those end up on unrelated domains, the
cookie becomes cross-site, and a cross-site cookie must carry
`SameSite=None` — which gives up the CSRF protection `SameSite=Lax` provides
for free.

## Decision

```
httpOnly   yes, for the session cookie
Secure     yes
SameSite   Lax
Path       /
Domain     absent — host-only
```

**httpOnly**: JavaScript cannot read the session cookie, so an XSS that runs
in the page still cannot exfiltrate the session. The CSRF cookie is
deliberately *not* httpOnly, because the double-submit pattern requires the
page to copy it into a header — its value is not that it is secret, but that
another origin cannot read it.

**No Domain attribute.** A cookie with `Domain=leka.xx` is sent to every
subdomain, including any we do not control — a marketing site on a shared
platform, a status page, a subdomain someone forgets to decommission. Leaving
it out keeps the cookie host-only.

**SameSite=Lax, and therefore a parent-domain requirement.** Lax means a
cross-site POST does not carry the cookie, which is CSRF protection we get
for free given that every mutation we serve is POST, PATCH or DELETE.

Keeping it requires the frontend and the API to share a parent domain:
`app.leka.xx` and `api.leka.xx`. **This is a deployment requirement, not a
preference.** It is cheap to satisfy on day one and expensive to retrofit.

The value is configurable, and the application **refuses to start** in
production with `SameSite=None` or `Secure=false`. A warning in a startup log
is a warning nobody reads.

**Double-submit CSRF tokens anyway.** A second cookie, readable by the page,
whose value must be echoed in an `X-CSRF-Token` header on every mutation.
Enforced by middleware rather than per route, so a route added next year is
covered without its author knowing the check exists. Today it is defence in
depth; if the cookie ever has to become `SameSite=None`, it is the only
protection left.

## Alternatives rejected

**SameSite=None from the start, to keep deployment flexible.**
Buys freedom in choosing hosts, and pays with the loss of the one CSRF
protection that cannot be forgotten. Given that the parent-domain setup costs
one DNS record, this is a bad trade.

**SameSite=Strict.**
Stronger, and it breaks the ordinary case of following a link into the
application from an email — including our own verification and reset links,
where the user would arrive signed out and confused. Lax exists for exactly
this.

**A token in `localStorage` and an `Authorization` header.**
Avoids CSRF entirely, since nothing is sent automatically. Trades it for
something worse: `localStorage` is readable by any script on the page, so an
XSS becomes a full account takeover. httpOnly cookies are the only storage a
script cannot read.

**Setting `Domain=.leka.xx` so subdomains share the session.**
Convenient right up to the day a subdomain is compromised or handed to a
third party, at which point it has our customers' sessions.

## Consequences

**Good.** CSRF is covered twice, by an attribute that cannot be forgotten and
by a token that survives if the attribute changes. XSS cannot read the
session. The cookie does not spread across subdomains. A production
misconfiguration stops the deploy rather than shipping.

**Bad.** The deployment is constrained: frontend and API must share a parent
domain, which rules out the simplest Vercel-plus-Railway defaults. Local
development needs `LEKA_SESSION_COOKIE_SECURE=false`, which is refused in
production — an asymmetry that will confuse somebody once.

**Watch for:** anyone proposing `SameSite=None` to unblock a deployment. The
answer is a DNS record, not a cookie attribute. If it genuinely becomes
unavoidable, the double-submit token becomes load-bearing and deserves a
second look.
