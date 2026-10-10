"""Sensitive data, recognised (LEKA-405), pure.

What these protect: every vendor's token LEKA knows by its shape, a private
key, a password in a URL or a setting — found and taken out; what only
names a secret (`${DB_PASSWORD}`, `<password>`, a variable) left alone; a
quoted value always one; personal data — addresses and phones counted and
kept, an IBAN, a card, a French social security number taken out — and only
when its issuer's check says it is one: a timestamp is not a card, sixteen
digits that do not add up are not one; a record as JSON protected through
and through, keys included, its findings counted, never a value; what a
person types guarded; a vendor's error cleaned by the same detector.
"""

from __future__ import annotations

import pytest

from leka.connectors.errors import sanitise
from leka.core.sensitive import (
    PERSONAL_DATA,
    SECRETS,
    SENSITIVE_VERSION,
    guarded,
    protect,
    redacted,
    scan,
)


def _nir() -> str:
    body = "1850578006084"
    return f"1 85 05 78 006 084 {97 - int(body) % 97:02d}"


SECRETS_SAID = [
    ("AKIAIOSFODNN7EXAMPLE", "aws_key"),
    ("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "aws_secret"),
    ("ghp_" + "a" * 36, "github_token"),
    ("github_pat_" + "A1" * 20, "github_token"),
    ("glpat-" + "x" * 20, "gitlab_token"),
    ("ATATT" + "3xFfGF0" * 4, "atlassian_token"),
    ("xoxb-1234567890-abcdefghij", "slack_token"),
    ("https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXXXXXX", "slack_webhook"),
    ("AIza" + "S" * 35, "google_key"),
    ("sk-proj-" + "a1B2" * 8, "api_key"),
    ("sk-ant-api03-" + "z9" * 20, "api_key"),
    ("sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc", "stripe_key"),
    ("lin_api_" + "k" * 20, "linear_key"),
    ("ntn_" + "1" * 40, "notion_token"),
    ("npm_" + "a" * 36, "npm_token"),
    ("pypi-" + "A" * 60, "pypi_token"),
    ("hf_" + "b" * 34, "huggingface_token"),
    ("dckr_pat_" + "c" * 27, "docker_token"),
    ("SG." + "d" * 22 + "." + "e" * 43, "sendgrid_key"),
    (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "jwt",
    ),
    ("DefaultEndpointsProtocol=https;AccountKey=" + "Q" * 86 + "==", "azure_key"),
    ("postgresql://leka:S3cr3t-pw@db:5432/leka", "connection_string"),
    ('password: "letmeinplease"', "password"),
    ("DB_PASSWORD=hunter2xyz", "password"),
    ('"client_secret": "abc123def456"', "password"),
    ("mot de passe : Sup3rS3cret!", "password"),
    ('mdp="azerty123"', "password"),
    ("clé API = Zx9-77-aa-bb", "password"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "private_key"),
]


@pytest.mark.parametrize(("text", "what"), SECRETS_SAID)
def test_a_secret_is_found_by_its_shape_and_taken_out(text: str, what: str) -> None:
    found = scan(f"before {text} after")
    assert [(f.detect, f.what) for f in found] == [(SECRETS, what)]
    out = redacted(f"before {text} after", found)
    assert f"[redacted:{what}]" in out
    assert out.startswith("before ")
    assert out.endswith(" after")


def test_what_only_names_a_secret_is_not_one() -> None:
    for text in (
        "postgres://user:${PASSWORD}@db/app",
        "postgresql+asyncpg://user:password@host/db",
        "password: user_password",
        "pwd=self.pwd",
        "api_key = settings.api_key",
        "password = get_password()",
        "PASSWORD=<your password here>",
        "secret: ******",
        "the secrets and passwords chapter, version 2.4.1, port 5432",
    ):
        assert scan(text, (SECRETS,)) == [], text


def test_personal_data_is_counted_and_identity_numbers_taken_out() -> None:
    text = (
        f"Ada <ada@acme.io>, +33 6 12 34 56 78 or 06 12 34 56 78, "
        f"IBAN FR76 3000 6000 0112 3456 7890 189, card 4111 1111 1111 1111, NIR {_nir()}"
    )
    found = scan(text)
    assert [(f.detect, f.what) for f in found] == [
        (PERSONAL_DATA, "email"),
        (PERSONAL_DATA, "phone"),
        (PERSONAL_DATA, "phone"),
        (PERSONAL_DATA, "iban"),
        (PERSONAL_DATA, "card"),
        (PERSONAL_DATA, "fr_nir"),
    ]
    kept = guarded(text)
    assert "ada@acme.io" in kept
    assert "06 12 34 56 78" in kept
    assert "[redacted:iban]" in kept
    assert "[redacted:card]" in kept
    assert "[redacted:fr_nir]" in kept


def test_a_number_is_an_identity_number_only_when_its_check_says_so() -> None:
    # Luhn fails; a timestamp in milliseconds; an IBAN off by one; a NIR
    # with the wrong key.
    nir = _nir()
    wrong_key = nir[:-2] + f"{(int(nir[-2:]) + 1) % 97:02d}"
    for text in (
        "4111 1111 1111 1112",
        "ts 1728547200000",
        "FR76 3000 6000 0112 3456 7890 188",
        wrong_key,
    ):
        assert [f.what for f in scan(text) if f.what in ("card", "iban", "fr_nir")] == [], text


def test_a_record_is_protected_through_and_through() -> None:
    record = {
        "title": "creds AKIAIOSFODNN7EXAMPLE",
        "contents": [{"role": "body", "text": "mail ada@acme.io card 4111111111111111"}],
        "metadata": {"DB_PASSWORD=hunter2xyz": True, "count": 3, "none": None},
    }
    kept = protect(record)
    assert kept.value == {
        "title": "creds [redacted:aws_key]",
        "contents": [{"role": "body", "text": "mail ada@acme.io card [redacted:card]"}],
        "metadata": {"DB_PASSWORD=[redacted:password]": True, "count": 3, "none": None},
    }
    assert kept.summary() == {
        "version": SENSITIVE_VERSION,
        "secrets": {"aws_key": 1, "password": 1},
        "personal_data": {"card": 1, "email": 1},
    }
    # Nothing found: the same value, nothing counted.
    clean = protect({"title": "Billing API is slow"})
    assert clean.value == {"title": "Billing API is slow"}
    assert not clean.found


def test_a_vendor_error_is_cleaned_by_the_same_detector() -> None:
    said = sanitise("401: key AKIAIOSFODNN7EXAMPLE refused for hf_" + "b" * 34)
    assert "AKIA" not in said
    assert "hf_" not in said
