"""What the database connectors share (leka/connectors/databases.py)."""

from __future__ import annotations

import pytest

from leka.connectors import DiagnosticCode
from leka.connectors.databases import public_host, rounded, schema_names, too_many_tables


@pytest.mark.parametrize(
    ("number", "kept"),
    [(None, None), (0, 0), (42, 42), (8192, 8200), (12_345_678, 12_000_000), (99_999, 100_000)],
)
def test_estimates_keep_two_figures(number: int | None, kept: int | None) -> None:
    assert rounded(number) == kept


def test_schema_names_are_trimmed_once_each_and_bounded() -> None:
    assert schema_names(None, 63) is None
    assert schema_names([" billing", "billing", "ops"], 63) == ["billing", "ops"]
    for wrong in ([""], ["x" * 64], ["a\x00b"]):
        with pytest.raises(ValueError, match="not a schema name"):
            schema_names(wrong, 63)


def test_a_host_is_tidied_and_a_plainly_private_one_refused() -> None:
    assert public_host(" DB.Acme.Example ") == "db.acme.example"
    assert public_host("140.82.112.6") == "140.82.112.6"
    for private in ("10.0.0.5", "127.0.0.1", "[::1]", "169.254.169.254"):
        with pytest.raises(ValueError, match="not a public address"):
            public_host(private)


def test_too_many_tables_asks_for_a_scope() -> None:
    diagnostic = too_many_tables().diagnostic

    assert diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "20\u202f000" in diagnostic.message
