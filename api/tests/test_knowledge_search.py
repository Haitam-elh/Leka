"""What search reads of an entity, and what it makes of what was typed
(LEKA-369). The pure part: search.py; test_knowledge_graph.py searches
PostgreSQL through the API.

What these protect: words are found whatever their accents, case and
punctuation — "equipe donnees" finds Équipe Données, "oeuvre" main-d'œuvre —
and no script's letters are lost; a word's case changes do not break it —
"postgresql" finds PostgreSQL, "github" GitHub — but its pieces are words
too: "payment api" and "api" find PaymentApi; an entity's names are kept
apart from its other words, each once, and apart from one another; what is
typed becomes a tsquery of prefixes that nothing typed can break; long
texts are cut, not refused.
"""

from __future__ import annotations

import pytest

from leka.knowledge.search import (
    MAX_DESCRIPTION,
    MAX_TEXT,
    MAX_WORDS,
    NAMES_APART,
    fields,
    fold,
    pieces,
    query,
)


@pytest.mark.parametrize(
    ("typed", "folded"),
    [
        ("Équipe Données", "equipe donnees"),
        ("payment-api", "payment api"),
        ("nora@acme.io", "nora acme io"),
        ("  Ça   marche !  ", "ca marche"),
        ("Main-d'œuvre", "main d oeuvre"),
        ("ŒUVRE naïve", "oeuvre naive"),
        ("Straße", "strasse"),
        ("snake_case", "snake case"),
        # Every script's letters are words: none is lost.
        ("Москва", "москва"),
        ("東京 office", "東京 office"),
        # A word's case changes do not break it.
        ("PostgreSQL", "postgresql"),
        ("PaymentAPI/v2", "paymentapi v2"),
        ("!!!", ""),
        ("", ""),
    ],
)
def test_words_are_folded_whatever_their_accents_case_and_punctuation(
    typed: str, folded: str
) -> None:
    assert fold(typed) == folded


@pytest.mark.parametrize(
    ("typed", "split"),
    [
        ("PaymentApi", "payment api"),
        ("PaymentAPIClient/v2", "payment api client v2"),
        ("getHTTPResponse2Code", "get http response2 code"),
        ("S3Bucket", "s3 bucket"),
        ("iOSApp", "i os app"),
    ],
)
def test_case_changes_break_words_when_asked(typed: str, split: str) -> None:
    assert fold(typed, cases=True) == split


def test_the_pieces_are_the_words_case_changes_make() -> None:
    assert pieces("PostgreSQL on GitHub") == ["postgre", "sql", "git", "hub"]
    assert pieces("payment api") == []
    assert pieces("PaymentApi", besides=["payment"]) == ["api"]


def test_names_are_kept_apart_from_the_other_words() -> None:
    name, text = fields(
        "github.com/acme/payment-api",
        "acme/payment-api",
        {
            "description": "Takes the payments",
            "topics": ["payments", 3, None],
            "language": "Python",
            "email": None,
            "stars": 12,
        },
    )

    # The full name, then the repository's own: payment-api of acme/payment-api.
    assert name == f"acme payment api{NAMES_APART}payment api"
    assert text == "github com acme payment api takes the payments python payments"


def test_each_name_once_its_pieces_with_the_other_words() -> None:
    name, text = fields(
        "service:billing", "BillingApi", {"display_name": "billingapi", "engine": "PostgreSQL"}
    )

    # The display name folds as the name does: said once, so the very name
    # typed is the whole of one.
    assert name == "billingapi"
    assert text == "service billing postgresql billing api postgre sql"


def test_what_says_what_a_thing_is_counts_its_attributes() -> None:
    _, text = fields(
        "aws:arn:aws:rds:eu-west-3:1:db:orders",
        "orders",
        {
            "engine": "PostgreSQL",
            "region": "eu-west-3",
            "environment": "production",
            "labels": ["Critique"],
            "tags": ["team:payments"],
        },
    )

    for word in ("postgresql", "eu west 3", "production", "critique", "team payments"):
        assert word in text


def test_long_texts_are_cut_not_refused() -> None:
    long = "word " * 2_000
    name, text = fields("document:long", long, {"description": "x" * 10_000})

    assert len(name) <= MAX_TEXT
    assert len(text) <= MAX_TEXT
    assert "x" * MAX_DESCRIPTION in text
    assert "x" * (MAX_DESCRIPTION + 1) not in text


@pytest.mark.parametrize(
    ("typed", "tsquery"),
    [
        ("Pay", "pay:*"),
        ("Équipe données", "equipe:* & donnees:*"),
        ("payment-api", "payment:* & api:*"),
        ("postgresql", "postgresql:*"),
        # Typed as it is written: the whole word, or its pieces.
        ("PaymentApi", "(paymentapi:*) | (payment:* & api:*)"),
        # tsquery's own syntax is not a word: nothing typed can break a query.
        ("a & b | !c <-> (d):*", "a:* & b:* & c:* & d:*"),
        ("'; DROP TABLE entities; --", "drop:* & table:* & entities:*"),
    ],
)
def test_every_word_typed_is_a_prefix_all_of_them_needed(typed: str, tsquery: str) -> None:
    assert query(typed) == tsquery


def test_nothing_searchable_is_no_query() -> None:
    assert query("") is None
    assert query("  !?! ") is None


def test_a_long_query_keeps_its_first_words() -> None:
    found = query(" ".join(f"w{n}" for n in range(20)))

    assert found is not None
    assert found.split(" & ") == [f"w{n}:*" for n in range(MAX_WORDS)]
