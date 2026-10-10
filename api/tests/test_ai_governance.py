"""AI governance (LEKA-406), decided — governance/ai.py, no database.

What these protect:
- A control covers the work it names (fnmatch purposes) and the roles it
  names; work done for nobody is covered only by controls naming no role.
- Model access: every control covering the work must allow the model — a
  block allows none.
- A usage limit says what of it is reached: calls, tokens, cost.
- An answer is looked through for secrets and personal data — a card only
  when its digits pass Luhn — redacted once where findings overlap; a block
  wins over a redaction; a flag keeps the text as it is.
- An agent at or above an approval control's risk is held; below, not.
- A control that cannot be kept says which field, and why.
"""

from __future__ import annotations

import uuid

import pytest

from leka.governance import (
    Actor,
    Control,
    ControlError,
    Used,
    check_output,
    checked_control,
    control_of,
    covers,
    holding,
    limits,
    refusing,
    scan,
    spent,
)
from leka.governance.ai import REDACTED, redacted

MEMBER = Actor(uuid.uuid4(), frozenset({"member"}))
LEAD = Actor(uuid.uuid4(), frozenset({"member", "tech-lead"}))


def _control(kind: str, **config: object) -> Control:
    purposes = config.pop("purposes", ())
    roles = config.pop("roles", ())
    return control_of("c", kind, config, purposes=purposes, roles=roles)  # type: ignore[arg-type]


# ── what a control covers ──────────────────────────────────────────────────


def test_a_control_covers_its_purposes_and_its_roles() -> None:
    agents = _control("approval", purposes=["agent:*"])
    assert covers(agents, "agent:security-review", MEMBER)
    assert not covers(agents, "intention.answer", MEMBER)
    everything = _control("approval")
    assert covers(everything, "intention.answer", None)

    members = _control("approval", roles=["member"])
    leads = _control("approval", roles=["tech-lead"])
    assert covers(members, "x", MEMBER) and covers(members, "x", LEAD)
    assert not covers(leads, "x", MEMBER) and covers(leads, "x", LEAD)
    # Done for nobody: only a control naming no role covers it.
    assert not covers(members, "x", None)


# ── which model ────────────────────────────────────────────────────────────


def test_every_control_covering_the_work_must_allow_the_model() -> None:
    only_mistral = _control("model_access", providers=["mistral"])
    own_account = _control("model_access", owners=["workspace"], purposes=["agent:*"])
    controls = [only_mistral, own_account]
    assert refusing(controls, "intention.answer", MEMBER, provider="mistral", owner="leka") is None
    assert (
        refusing(controls, "intention.answer", MEMBER, provider="google", owner="leka")
        is only_mistral
    )
    # An agent: on the workspace's own account only.
    assert (
        refusing(controls, "agent:code-review", MEMBER, provider="mistral", owner="leka")
        is own_account
    )
    assert (
        refusing(controls, "agent:code-review", MEMBER, provider="mistral", owner="workspace")
        is None
    )

    none_for_members = _control("model_access", block=True, roles=["member"])
    assert refusing([none_for_members], "x", MEMBER, provider="google", owner="leka") is not None
    assert refusing([none_for_members], "x", None, provider="google", owner="leka") is None


# ── how much ───────────────────────────────────────────────────────────────


def test_a_limit_says_what_of_it_is_reached() -> None:
    limit = _control("usage_limit", max_calls=10, max_tokens=5000, max_cost_usd=1.5)
    assert spent(limit, Used(calls=9, tokens=4999, cost_usd=1.49)) is None
    assert spent(limit, Used(calls=10)) == "calls"
    assert spent(limit, Used(calls=1, tokens=5000)) == "tokens"
    assert spent(limit, Used(calls=1, tokens=1, cost_usd=1.5)) == "cost"

    per_person = _control("usage_limit", per="person", max_calls=3, roles=["member"])
    other = _control("model_access", providers=["google"])
    assert limits([per_person, other], "x", MEMBER) == [per_person]
    assert limits([per_person, other], "x", None) == []


# ── what an answer carries ─────────────────────────────────────────────────

SECRETS = frozenset({"secrets"})
PERSONAL = frozenset({"personal_data"})


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("key AKIAIOSFODNN7EXAMPLE here", "aws_key"),
        ("token ghp_" + "a" * 36, "github_token"),
        ("sk-ant-" + "b" * 30, "api_key"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
        ('password: "hunter2-long"', "password"),
        ("xoxb-1234567890-abcdef", "slack_token"),
    ],
)
def test_secrets_are_found(text: str, what: str) -> None:
    assert [f.what for f in scan(text, SECRETS)] == [what]


def test_personal_data_is_found_a_card_only_when_luhn_says_so() -> None:
    found = scan(
        "Écrire à jean.dupont@acme.fr, 06 12 34 56 78, IBAN FR76 3000 6000 0112 3456 7890 189",
        PERSONAL,
    )
    assert {f.what for f in found} == {"email", "phone", "iban"}
    assert [f.what for f in scan("carte 4111 1111 1111 1111", PERSONAL)] == ["card"]
    # Sixteen digits that are no card: a reference, kept.
    assert scan("commande 4111 1111 1111 1112", PERSONAL) == []
    # Looked for what is asked only.
    assert scan("jean.dupont@acme.fr", SECRETS) == []


def test_a_password_keeps_its_name_and_loses_its_value() -> None:
    text = "password=hunter2-long; reste"
    assert redacted(text, scan(text, SECRETS)) == f"password={REDACTED}; reste"


def test_overlapping_findings_are_redacted_once() -> None:
    text = "a: 4111 1111 1111 1111 b"
    found = scan(text, PERSONAL)
    assert redacted(text, found).count(REDACTED) == 1


def test_a_block_wins_redactions_follow_one_another_a_flag_keeps_the_text() -> None:
    redact_secrets = control_of("Secrets", "output_check", {"detect": ["secrets"]})
    flag_personal = control_of(
        "Personnel", "output_check", {"detect": ["personal_data"], "on_finding": "flag"}
    )
    text = "AKIAIOSFODNN7EXAMPLE pour jean@acme.fr"
    checked = check_output([redact_secrets, flag_personal], "x", None, text)
    assert checked.text == f"{REDACTED} pour jean@acme.fr"
    assert [(c.name, o, w) for c, o, w in checked.outcomes] == [
        ("Secrets", "redacted", ("aws_key",)),
        ("Personnel", "flagged", ("email",)),
    ]
    assert checked.blocked_by is None

    block = control_of(
        "Bloquer", "output_check", {"detect": ["personal_data"], "on_finding": "block"}
    )
    assert check_output([block], "x", None, text).blocked_by is block
    # Nothing found: nothing said.
    assert check_output([block], "x", None, "rien ici").outcomes == ()


# ── approval ───────────────────────────────────────────────────────────────


def test_an_agent_at_or_above_the_risk_is_held() -> None:
    high = _control("approval", risk_at_least="high")
    medium_members = _control("approval", risk_at_least="medium", roles=["member"])
    assert holding([high], "security-review", "high", MEMBER) is high
    assert holding([high], "code-review", "medium", MEMBER) is None
    assert holding([medium_members], "code-review", "medium", MEMBER) is medium_members
    assert holding([medium_members], "code-review", "low", MEMBER) is None
    # A control for some agents only.
    one = control_of("x", "approval", {"risk_at_least": "low"}, purposes=["agent:code-*"])
    assert holding([one], "code-review", "low", None) is one
    assert holding([one], "security-review", "high", None) is None


# ── kept as given ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "config", "field"),
    [
        ("nope", {}, "kind"),
        ("model_access", {}, "providers"),
        ("model_access", {"owners": ["someone"]}, "owners"),
        ("usage_limit", {}, "max_calls"),
        ("usage_limit", {"max_calls": 1, "period": "week"}, "period"),
        ("output_check", {"detect": ["dreams"]}, "detect"),
        ("output_check", {"detect": ["secrets"], "on_finding": "shout"}, "on_finding"),
        ("approval", {"risk_at_least": "extreme"}, "risk_at_least"),
    ],
)
def test_a_control_that_cannot_be_kept_says_which_field(
    kind: str, config: dict[str, object], field: str
) -> None:
    with pytest.raises(ControlError) as raised:
        checked_control(control_of("Un contrôle", kind, config))
    assert raised.value.field == field


def test_a_purpose_with_a_space_is_refused_and_a_nameless_control() -> None:
    with pytest.raises(ControlError) as raised:
        checked_control(control_of("x", "approval", {}, purposes=["agent: x"]))
    assert raised.value.field == "purposes"
    with pytest.raises(ControlError) as raised:
        checked_control(control_of("  ", "approval", {}))
    assert raised.value.field == "name"


def test_what_is_kept_is_its_kind_s_own() -> None:
    control = control_of(
        "x", "usage_limit", {"max_calls": 3, "detect": ["secrets"], "providers": ["google"]}
    )
    assert control.config() == {
        "period": "day",
        "per": "workspace",
        "max_calls": 3,
        "max_tokens": None,
        "max_cost_usd": None,
    }
