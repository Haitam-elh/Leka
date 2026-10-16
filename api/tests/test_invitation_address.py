"""An invitation's address (LEKA-469): checked shallowly, but never with
whitespace or a control character inside — such an address was taken,
then mailed."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from leka.platform.schemas import InvitationCreate


def test_an_address_is_trimmed_and_lowered() -> None:
    assert InvitationCreate(email="  Nora@Acme.example ").email == "nora@acme.example"


@pytest.mark.parametrize(
    "email",
    [
        "nora@acme.example\nfdd7f4d8",
        "nora @acme.example",
        "nora@acme.example\tx",
        "nora@acme\x00.example",
    ],
)
def test_whitespace_or_a_control_character_inside_is_refused(email: str) -> None:
    with pytest.raises(ValidationError):
        InvitationCreate(email=email)
