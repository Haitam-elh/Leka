"""What tells two candidates together, or apart (LEKA-357): pure functions
of their keys and their names.

DETERMINISTIC — what a key itself says:

    github noreply   12345+sara@users.noreply.github.com is GitHub's `sara`
    gitlab noreply   12-sara@users.noreply.gitlab.com is GitLab's `sara`
    plus address     sara+jira@acme.io is sara@acme.io's mailbox

SEMANTIC — what names mean, compared locally (no model, no service):

    person   a full name, in any order: "Martin Sara" is "Sara Martin"
             a handle — a login, an address's local part — read as a name:
             sara.martin, martin_sara, saramartin (0.85, 0.8), smartin (0.55)
             the same handle in two tools (0.75)
    service  a name's core: "Billing API", billing-service, billing,
             payments/payment — the words that say "a service", "a team",
             and a plural, set aside; an environment word (billing-staging)
             is a variant, not the same; a typo is a resemblance

Everything here is a signal, with a weight; what is decided of them is
leka/ingestion/resolution/engine.py's. Rules: docs/resolution.md.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

GITHUB_NOREPLY = re.compile(
    r"^(?:\d+\+)?([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)@users\.noreply\.github\.com$"
)
GITLAB_NOREPLY = re.compile(r"^(?:\d+-)?([a-z0-9._-]+)@users\.noreply\.gitlab\.com$")
PLUS = re.compile(r"^([^+@]+)\+[^@]*@(.+)$")
NOREPLY = re.compile(r"(?i)(^|[._-])no-?reply([._-]|@)|@users\.noreply\.")

# Accounts no person is: they commit, comment and deploy for everyone.
BOT = re.compile(
    r"(?i)(\[bot\]|(^|[-_.])bot($|[-_.@])|dependabot|renovate|github-actions|gitlab-ci|"
    r"jenkins|circleci|snyk|sonar|travis|buildkite|argocd|terraform|"
    # A service's own address — noreply@github.com signs GitHub's merges,
    # noreply@anthropic.com an assistant's co-authored commits — and the
    # account GitHub merges as. Not a person's private address,
    # 12345+sara@users.noreply.github.com: that one is Sara's (above).
    r"(^|[:<\s])no-?reply@|(^|[:/])web-flow$)"
)
# Handles too common to say who someone is: an "admin" in two tools is no one.
GENERIC_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "root",
        "user",
        "test",
        "tester",
        "dev",
        "developer",
        "ops",
        "info",
        "support",
        "contact",
        "hello",
        "team",
        "sales",
        "security",
        "system",
        "service",
        "deploy",
        "release",
        "noreply",
        "guest",
        "demo",
    }
)
# The last words of a name that say what it is, not which one it is.
SERVICE_WORDS = frozenset({"api", "service", "svc", "srv", "app", "server", "ms", "microservice"})
# An application's: "Billing platform" is Billing (LEKA-362).
APPLICATION_WORDS = frozenset({"app", "application", "platform", "system", "product", "suite"})
TEAM_WORDS = frozenset({"team", "squad", "group", "crew", "guild", "tribe", "eng", "engineering"})
ENVIRONMENTS = frozenset(
    {
        "prod",
        "production",
        "prd",
        "staging",
        "stage",
        "stg",
        "preprod",
        "dev",
        "development",
        "qa",
        "uat",
        "sandbox",
    }
)
MIN_HANDLE = 4
TYPO_RATIO = 0.9
TYPO_MIN = 6


def fold(text: str) -> str:
    """Lower case, no accents, words single-spaced: 'Sara  Martín' → 'sara martin'."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.lower()).split())


def words(text: str) -> list[str]:
    return fold(text).split()


# ── keys ─────────────────────────────────────────────────────────────────────


def email_of(key: str) -> str | None:
    """The address a person's key holds: person:email:<address>."""
    return key.removeprefix("person:email:") if key.startswith("person:email:") else None


def account_of(key: str) -> tuple[str, str] | None:
    """(host, account) of a person's account key: person:github.com:sara."""
    if not key.startswith("person:") or key.startswith("person:email:"):
        return None
    host, _, account = key.removeprefix("person:").partition(":")
    return (host, account) if host and account else None


def derived(key: str) -> list[tuple[str, str, float]]:
    """Keys a person's address itself says it is: (key, rule, confidence)."""
    email = email_of(key)
    if email is None:
        return []
    found: list[tuple[str, str, float]] = []
    if hub := GITHUB_NOREPLY.match(email):
        found.append((f"person:github.com:{hub.group(1)}", "github_noreply", 0.99))
    elif lab := GITLAB_NOREPLY.match(email):
        found.append((f"person:gitlab.com:{lab.group(1)}", "gitlab_noreply", 0.99))
    elif plus := PLUS.match(email):
        found.append((f"person:email:{plus.group(1)}@{plus.group(2)}", "plus_address", 0.95))
    return found


def opaque(account: str) -> bool:
    """An account id that is no one's handle: a Jira account id, a uuid."""
    return (
        ":" in account
        or account.startswith("{")
        or bool(re.fullmatch(r"[0-9a-f-]{16,}", account))
        or sum(c.isdigit() for c in account) > len(account) / 2
    )


def handles(key: str) -> set[str]:
    """What a person is called in tools: a login, an address's local part —
    without separators, lower-cased. None generic, none opaque, none a
    no-reply address's."""
    found: set[str] = set()
    if (email := email_of(key)) is not None:
        if NOREPLY.search(email):
            return found
        local = email.split("@")[0].split("+")[0]
        found.add(local)
    elif (account := account_of(key)) is not None:
        if not opaque(account[1]):
            found.add(account[1].lower())
    return {
        squeezed
        for handle in found
        if len(squeezed := re.sub(r"[^a-z0-9]", "", fold(handle))) >= MIN_HANDLE
        and squeezed not in GENERIC_HANDLES
    }


def handle_parts(key: str) -> list[list[str]]:
    """A handle's words, where it has separators: sara.martin → [sara, martin]."""
    parts = []
    email = email_of(key)
    raw = email.split("@")[0].split("+")[0] if email else (account_of(key) or ("", ""))[1]
    if raw and re.search(r"[._-]", raw) and not opaque(raw):
        parts.append(words(raw))
    return parts


def is_bot(key: str, name: str) -> bool:
    return bool(BOT.search(key) or BOT.search(name))


# ── people ───────────────────────────────────────────────────────────────────


def full_name(name: str) -> tuple[str, ...] | None:
    """A person's full name, its words in order-free form — or None when it
    is not one: a single word, an address, a handle, digits."""
    if "@" in name or re.search(r"\d", name):
        return None
    parts = words(name)
    if len(parts) < 2 or len(parts) > 5 or any(len(part) < 2 for part in parts):
        return None
    return tuple(sorted(parts))


def name_handles(name: tuple[str, ...]) -> dict[str, float]:
    """The handles a full name is written as, and how surely: saramartin,
    martinsara 0.8 — smartin, msara 0.55 (an initial and a surname: Sam
    Martin is smartin too, so alone with a same handle it links, not
    merges)."""
    first, *_, last = name
    found = {first + last: 0.8, last + first: 0.8}
    for given, family in ((first, last), (last, first)):
        found.setdefault(given[0] + family, 0.55)
    return found


def handle_reads_as(parts: list[str], name: tuple[str, ...]) -> bool:
    """sara.martin, martin_sara: a handle whose words are the name's."""
    return len(parts) >= 2 and tuple(sorted(parts)) == name


# ── services and teams ───────────────────────────────────────────────────────


def core(name: str, kind_words: frozenset[str]) -> tuple[str, str | None]:
    """A service's or a team's name, its core and its environment:
    'Billing API' → ('billing', None); 'payments-service-staging' →
    ('payment', 'staging'). Never empty: a name made only of those words
    keeps them."""
    parts = words(name.replace("service:", "").replace("team:", ""))
    environment = None
    if len(parts) > 1 and parts[-1] in ENVIRONMENTS:
        environment = parts.pop()
    while len(parts) > 1 and parts[-1] in kind_words:
        parts.pop()
    if parts:
        parts[-1] = singular(parts[-1])
    return "-".join(parts), environment


def singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def spelled_alike(left: str, right: str) -> bool:
    """A typo, not another thing: long enough, nearly the same letters, and
    no digit where they differ — payment-v1 and payment-v2 are two."""
    if min(len(left), len(right)) < TYPO_MIN or left == right:
        return False
    matcher = SequenceMatcher(None, left, right)
    if matcher.ratio() < TYPO_RATIO:
        return False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal" and re.search(r"\d", left[i1:i2] + right[j1:j2]):
            return False
    return True
