"""What every GraphQL connector does the same way — Linear, Monday.

A GraphQL vendor has one endpoint and answers everything through POST, so
"LEKA reads" cannot rest on the HTTP method there. It rests on the
documents: each is a constant in its connector and a `query`, and
`read_only` refuses a `mutation` or a `subscription` before it is sent.

A GraphQL vendor also refuses in two ways: an HTTP error, or a 200 whose
body carries `errors`. `errors_of` reads the second, so a connector maps
both to the same diagnostics.
"""

from __future__ import annotations

import re
from typing import Any

import httpx


def read_only(document: str, vendor: str) -> str:
    """The document, if it only reads: one `query`, no `mutation`, no
    `subscription`, not even in a comment."""
    text = re.sub(r"#[^\n]*", "", document).strip()
    if not text.startswith("query") or re.search(r"\b(mutation|subscription)\b", text):
        msg = f"LEKA sends {vendor} queries only: no mutation, no subscription"
        raise ValueError(msg)
    return text


def errors_of(response: httpx.Response) -> list[Any]:
    """The `errors` of a GraphQL answer, empty when it has none or is not JSON."""
    try:
        errors = response.json().get("errors")
    except (ValueError, AttributeError):
        return []
    return errors if isinstance(errors, list) else []
