"""Sensitive data, recognised in text (LEKA-405), pure: one detector for all
of LEKA — what a customer's records carry, what a vendor's error echoes,
what a model answers.

    scan(text, detect)       what it carries: each finding its family
                             (secrets, personal_data), what it is (aws_key,
                             iban…) and where — never its value
    redacted(text, found)    the text, what was found replaced by
                             [redacted:<what>]
    guarded(text)            what a person typed, as kept: what is taken
                             out taken out
    protect(value)           a record as JSON, every string in it scanned:
                             the secrets and the identity numbers taken out,
                             the rest counted (Protected)

SECRETS are credentials: a vendor's token by its shape (AWS, GitHub,
GitLab, Atlassian, Slack, Google, OpenAI and Anthropic, Stripe, Linear,
Notion, npm, PyPI, Hugging Face, Docker, SendGrid, JSON Web Tokens), a
private key, a password in a connection string or said in a setting
(`password: "…"`, `DB_PASSWORD=…`, « mot de passe : … »). A value that only names another —
`${DB_PASSWORD}`, `<password>`, a variable — is not one.

PERSONAL DATA: e-mail addresses and phone numbers — counted, kept: who
owns, who answers, is what a company model is about — and the numbers that
identify a person's money or person: an IBAN, a card, a French social
security number. Each of those is checked as its issuer checks it (mod 97,
Luhn, the NIR key): sixteen digits are a card only when they add up as one.

Never perfect, and not meant to be: a shape no rule knows passes. What is
found is taken out where the text is kept, so that no copy of it outlives
the original (docs/data-protection.md).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# Bumped when what is found changes: what was scanned before is scanned again.
SENSITIVE_VERSION = 1

SECRETS = "secrets"
PERSONAL_DATA = "personal_data"
DETECTS = (SECRETS, PERSONAL_DATA)

# Personal data taken out wherever it is kept, as secrets are: numbers that
# identify a person's money or person, of no use to understanding systems.
# Addresses and phone numbers are kept: who owns and who answers is.
TAKEN_OUT = frozenset({"iban", "card", "fr_nir"})

# A value that only names where the secret is: not the secret.
_PLACEHOLDER = re.compile(r"^(?:\$\{?|<|\{\{|%|\*{3,}|x{6,}|\.{3})", re.IGNORECASE)
# Unquoted, what code computes — a member, a call, an index — or a word
# without a digit, a name: `password: user_password`, `pwd=self.pwd`.
_EXPRESSION = re.compile(r"^(?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|[A-Za-z_]\w*[(\[]|[A-Za-z_-]+$)")
# The first digits a card network issues: Visa, Mastercard, American
# Express, Discover, JCB, Diners — a timestamp's 17… is none of them.
_CARD_NETWORKS = re.compile(r"^(?:4|5[1-5]|2[2-7]|3[47]|6(?:011|5)|35|30[0-5]|36|38)")

# In English, and as LEKA's users say it: « mot de passe : … », « mdp=… ».
_SAID = (
    r"(?:password|passwd|pwd|passphrase|secret|client[_-]?secret|api[_-]?key"
    r"|access[_-]?token|auth[_-]?token|private[_-]?key"
    r"|mot[ _-]de[ _-]passe|motdepasse|mdp|cl[ée][ _-]api|cl[ée][ _-]priv[ée]e)"
)
# Said in a setting, bare: DB_PASSWORD=it, password: it — checked against
# what code computes (_EXPRESSION); quoted, a value is always one.
_BARE_SETTING = re.compile(rf"(?i)\b[\w.-]*{_SAID}\b\s*[:=]\s*([^\s\"'\\,;)\]}}]{{6,}})")

# Each: what it is, its pattern — the value alone when the pattern has a group.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
        ),
    ),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "aws_secret",
        re.compile(r"(?i)aws_secret_access_key\W{0,3}[:=]\s*[\"']?([A-Za-z0-9/+=]{40})\b"),
    ),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    (
        "gitlab_token",
        re.compile(r"\bgl(?:pat|oas|dt|rt|cbt|ptt|ft|imt|soat|ffct|agent)-[A-Za-z0-9_\-]{20,}"),
    ),
    ("atlassian_token", re.compile(r"\bAT(?:ATT|CTT|BB)[A-Za-z0-9_\-=]{16,}")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("slack_webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("api_key", re.compile(r"\bsk-(?:ant-[a-z0-9]+-|proj-)?[A-Za-z0-9_-]{24,}")),
    ("stripe_key", re.compile(r"\b(?:sk|rk|whsec)_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("linear_key", re.compile(r"\blin_(?:api|oauth)_[A-Za-z0-9]{16,}")),
    ("notion_token", re.compile(r"\b(?:ntn|secret)_[A-Za-z0-9]{32,}")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("pypi_token", re.compile(r"\bpypi-[A-Za-z0-9_-]{50,}")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("docker_token", re.compile(r"\bdckr_pat_[A-Za-z0-9_-]{20,}")),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("azure_key", re.compile(r"(?i)\bAccountKey=([A-Za-z0-9+/=]{40,})")),
    # A password in a URL: postgres://user:it@host — the password alone.
    ("connection_string", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s@/]{3,})@")),
    # Said in a setting, quoted: password: "it", "api_key": 'it'.
    (
        "password",
        re.compile(rf"(?i)\b[\w.-]*{_SAID}\b[\"']?\s*[:=]\s*[\"']([^\"'\s]{{6,}})[\"']"),
    ),
    ("password", _BARE_SETTING),
)

PERSONAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("card", re.compile(r"\b\d(?:[ -]?\d){12,18}\b")),
    (
        "fr_nir",
        re.compile(
            r"\b[12] ?\d{2} ?(?:0[1-9]|1[0-2]|[2-9]\d) ?(?:\d{2}|2[AB]) ?\d{3} ?\d{3} ?\d{2}\b"
        ),
    ),
    ("phone", re.compile(r"(?<![\w+])(?:\+|00)[1-9]\d{0,2}(?:[ .-]?\d){8,12}\b")),
    ("phone", re.compile(r"\b0[1-9](?:[ .-]?\d{2}){4}\b")),
)

PATTERNS: Mapping[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    SECRETS: SECRET_PATTERNS,
    PERSONAL_DATA: PERSONAL_PATTERNS,
}


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _iban(said: str) -> bool:
    """As banks check it: moved, lettered, mod 97 is 1."""
    value = said.replace(" ", "")
    if not 15 <= len(value) <= 34:
        return False
    moved = value[4:] + value[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def _nir(said: str) -> bool:
    """As the French social security checks it: its key is 97 less the
    number mod 97 — Corsica's 2A and 2B read as 19 and 18."""
    value = said.replace(" ", "")
    body, key = value[:13], value[13:]
    body = body.replace("2A", "19").replace("2B", "18")
    return body.isdigit() and int(key) == 97 - int(body) % 97


def _valid(what: str, said: str, pattern: re.Pattern[str]) -> bool:
    if what == "card":
        digits = re.sub(r"\D", "", said)
        return 13 <= len(digits) <= 19 and bool(_CARD_NETWORKS.match(digits)) and _luhn(digits)
    if what == "iban":
        return _iban(said)
    if what == "fr_nir":
        return _nir(said)
    if what in ("password", "connection_string"):
        if _PLACEHOLDER.match(said):
            return False
        return not (pattern is _BARE_SETTING or what == "connection_string") or not (
            _EXPRESSION.match(said)
        )
    return True


@dataclass(frozen=True)
class Finding:
    detect: str  # secrets, personal_data
    what: str  # aws_key, iban…
    start: int
    end: int


def scan(text: str, detect: Iterable[str] = DETECTS) -> list[Finding]:
    """What the text carries of what is looked for — never what it is; the
    longest first where two overlap."""
    wanted = frozenset(detect)
    found: list[Finding] = []
    for family in DETECTS:
        if family not in wanted:
            continue
        for what, pattern in PATTERNS[family]:
            for match in pattern.finditer(text):
                start, end = match.span(1) if pattern.groups else match.span()
                if start < 0 or not _valid(what, text[start:end], pattern):
                    continue
                found.append(Finding(family, what, start, end))
    found.sort(key=lambda f: (f.start, -f.end))
    kept: list[Finding] = []
    for finding in found:
        if kept and finding.start < kept[-1].end:
            continue  # inside one already found
        kept.append(finding)
    return kept


def redacted(text: str, found: Sequence[Finding]) -> str:
    """The text, what was found replaced by [redacted:<what>] — overlaps once."""
    out: list[str] = []
    at = 0
    for f in sorted(found, key=lambda f: f.start):
        if f.end <= at:
            continue
        out.append(text[at : max(at, f.start)])
        out.append(f"[redacted:{f.what}]")
        at = f.end
    out.append(text[at:])
    return "".join(out)


def taken_out(finding: Finding) -> bool:
    """Whether it is taken out where text is kept: every secret, and the
    numbers that identify a person's money or person."""
    return finding.detect == SECRETS or finding.what in TAKEN_OUT


def guarded(text: str) -> str:
    """What a person typed, as kept: the secrets and identity numbers in it
    taken out — an intention asked with a password in it keeps none."""
    out = [f for f in scan(text) if taken_out(f)]
    return redacted(text, out) if out else text


@dataclass
class Protected:
    """A value, protected: what was taken out, what was only counted."""

    value: object
    secrets: Counter[str] = field(default_factory=Counter)
    personal_data: Counter[str] = field(default_factory=Counter)

    @property
    def found(self) -> bool:
        return bool(self.secrets or self.personal_data)

    def summary(self) -> dict[str, object]:
        """As kept with the record: counts by kind, never a value."""
        return {
            "version": SENSITIVE_VERSION,
            "secrets": dict(sorted(self.secrets.items())),
            "personal_data": dict(sorted(self.personal_data.items())),
        }


def protect(value: object) -> Protected:
    """A record as JSON, every string in it — keys included — scanned: the
    secrets and the identity numbers replaced, everything found counted."""
    secrets: Counter[str] = Counter()
    personal: Counter[str] = Counter()

    def text(said: str) -> str:
        found = scan(said)
        if not found:
            return said
        for f in found:
            (secrets if f.detect == SECRETS else personal)[f.what] += 1
        out = [f for f in found if taken_out(f)]
        return redacted(said, out) if out else said

    def walk(node: object) -> object:
        if isinstance(node, str):
            return text(node)
        if isinstance(node, Mapping):
            return {text(str(k)) if isinstance(k, str) else k: walk(v) for k, v in node.items()}
        if isinstance(node, list | tuple):
            return [walk(v) for v in node]
        return node

    return Protected(walk(value), secrets, personal)


__all__ = [
    "DETECTS",
    "PERSONAL_DATA",
    "SECRETS",
    "SENSITIVE_VERSION",
    "TAKEN_OUT",
    "Finding",
    "Protected",
    "guarded",
    "protect",
    "redacted",
    "scan",
    "taken_out",
]
