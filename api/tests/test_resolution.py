"""Entity resolution, the rules (LEKA-357): which candidates are one thing.

Candidates as the connectors' normalisation gives them — GitHub, Jira,
Linear, PagerDuty, Datadog, a custom tool — and what resolution makes of
them. Each case is one the company model would get wrong otherwise:

- FALSE NEGATIVES, things that are one and must be found one: a person by
  their address and by their login, a GitHub no-reply address, a plus
  address, a Jira issue and the ticket a pull request names, a service
  spelled three ways, a team with its word "team".
- FALSE POSITIVES, things that are two and must stay two: namesakes with
  their own addresses, a ticket key in two tools, a shared account, bots,
  generic handles, a crowd of namesakes, services that only look alike, a
  tie.

And what is decided says how sure and why; what the sources disagree on
is kept, not overwritten. The job and the API: test_resolution_job.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from leka.ingestion.resolution import Identity, Mention, Resolution, resolve
from leka.ingestion.resolution import signals as sig

GITHUB = uuid.UUID("00000000-0000-0000-0000-00000000000a")
JIRA = uuid.UUID("00000000-0000-0000-0000-00000000000b")
LINEAR = uuid.UUID("00000000-0000-0000-0000-00000000000c")
PAGERDUTY = uuid.UUID("00000000-0000-0000-0000-00000000000d")
DATADOG = uuid.UUID("00000000-0000-0000-0000-00000000000e")
CUSTOM = uuid.UUID("00000000-0000-0000-0000-00000000000f")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def seen(
    key: str,
    source: uuid.UUID,
    name: str,
    *,
    type: str = "person",  # noqa: A002 — the candidate's own word
    aliases: tuple[str, ...] = (),
    record: bool = False,
    ago: int = 0,
    **attributes: Any,
) -> Mention:
    return Mention(
        key=key,
        type=type,
        source_id=source,
        name=name,
        aliases=set(aliases),
        attributes=attributes,
        first_seen=NOW - timedelta(days=30),
        last_seen=NOW - timedelta(hours=ago),
        records=1 if record else 0,
        named=0 if record else 1,
    )


def one(result: Resolution, key: str) -> Identity:
    found = [i for i in result.identities if key in {k.key for k in i.keys}]
    assert len(found) == 1, f"{key}: {len(found)} identities"
    return found[0]


def rules(identity: Identity, kind: str = "merge") -> set[str]:
    return {d.rule for d in identity.decisions if d.kind == kind}


def links(result: Resolution) -> list[tuple[str, str, str, float]]:
    return [
        (result.identities[i].key, result.identities[j].key, d.rule, d.confidence)
        for i, j, d in result.links
    ]


# ── false negatives: one thing, found one ────────────────────────────────────


def test_a_commit_author_by_address_and_a_pull_request_author_by_login_are_one() -> None:
    result = resolve(
        [
            seen(
                "person:email:sara@acme.io",
                GITHUB,
                "Sara Martin",
                aliases=("person:github.com:sara",),
            ),
            seen("person:github.com:sara", GITHUB, "sara"),
        ]
    )

    [sara] = result.identities
    assert (sara.key, sara.name, sara.confidence) == (
        "person:email:sara@acme.io",
        "Sara Martin",
        1.0,
    )
    assert rules(sara) == {"alias"}
    assert {(k.key, k.kind) for k in sara.keys} == {
        ("person:email:sara@acme.io", "key"),
        ("person:github.com:sara", "key"),
    }


def test_the_same_key_from_two_sources_is_one_thing_and_the_duplicate_is_said() -> None:
    result = resolve(
        [
            seen("service:billing-api", PAGERDUTY, "Billing API", type="service", record=True),
            seen("service:billing-api", DATADOG, "billing-api", type="service"),
        ]
    )

    [billing] = result.identities
    assert billing.sources == sorted([PAGERDUTY, DATADOG], key=str)
    [duplicate] = [d for d in billing.decisions if d.rule == "same_key"]
    assert (duplicate.confidence, duplicate.evidence) == (1.0, "seen by 2 sources")
    assert billing.name == "Billing API"  # its own record's name, not a tag's


def test_a_jira_issue_is_the_ticket_a_pull_request_names() -> None:
    result = resolve(
        [
            seen(
                "acme.atlassian.net/PAY-42",
                JIRA,
                "Refunds are doubled",
                type="issue",
                aliases=("ticket:PAY-42",),
                record=True,
            ),
            # A tool that names the ticket without its site.
            seen("ticket:PAY-42", CUSTOM, "PAY-42", type="issue"),
        ]
    )

    [issue] = result.identities
    assert issue.key == "acme.atlassian.net/PAY-42"
    assert issue.name == "Refunds are doubled"
    assert {(k.key, k.source_id, k.kind) for k in issue.keys} >= {
        ("ticket:PAY-42", JIRA, "alias"),
        ("ticket:PAY-42", CUSTOM, "key"),
    }


def test_a_github_no_reply_address_is_its_login() -> None:
    result = resolve(
        [
            seen("person:email:12345+sara@users.noreply.github.com", GITHUB, "Sara Martin"),
            seen("person:github.com:sara", GITHUB, "sara"),
        ]
    )

    [sara] = result.identities
    assert rules(sara) == {"github_noreply"}
    assert sara.confidence == 0.99
    # A no-reply address says who, but is no one's working address.
    assert sara.key == "person:github.com:sara"


def test_a_plus_address_is_its_mailbox() -> None:
    result = resolve(
        [
            seen("person:email:sara+jira@acme.io", JIRA, "Sara Martin"),
            seen("person:email:sara@acme.io", GITHUB, "Sara Martin"),
        ]
    )

    [sara] = result.identities
    assert (sara.key, sara.confidence, rules(sara)) == (
        "person:email:sara@acme.io",
        0.95,
        {"plus_address"},
    )
    assert any(k.kind == "derived" or k.key.endswith("sara@acme.io") for k in sara.keys)


def test_a_login_named_as_the_person_and_their_address_merge_across_tools() -> None:
    """GitHub knows her login and name, Jira her address: what she is
    called and how she signs in agree — two families of signals."""
    result = resolve(
        [
            seen("person:github.com:sara-martin", GITHUB, "Sara Martin"),
            seen("person:email:sara.martin@acme.io", JIRA, "Sara Martin"),
        ]
    )

    [sara] = result.identities
    assert sara.key == "person:email:sara.martin@acme.io"
    [merge] = [d for d in sara.decisions if d.kind == "merge"]
    assert merge.confidence == 0.95
    assert "same_full_name" in merge.rule or "handle_reads_as_name" in merge.rule
    assert "same_handle" in merge.rule
    assert sara.confidence == 0.95


def test_a_name_alone_links_a_jira_account_to_a_commit_author_it_does_not_merge() -> None:
    """Jira hides the address; a full name is one family of signals: a
    probable match, for the model to weigh — not a merge."""
    result = resolve(
        [
            seen("person:acme.atlassian.net:5b10ac8d82e05b22cc7d4ef5", JIRA, "Sara Martin"),
            seen("person:email:sara.martin@acme.io", GITHUB, "Sara Martin"),
        ]
    )

    assert len(result.identities) == 2
    [(_, _, rule, confidence)] = links(result)
    assert confidence == 0.85
    assert rule == "handle_reads_as_name"


def test_a_service_spelled_three_ways_is_one() -> None:
    result = resolve(
        [
            seen("service:billing-api", PAGERDUTY, "Billing API", type="service", record=True),
            seen("service:billing", DATADOG, "billing", type="service"),
            seen("service:billing-service", CUSTOM, "Billing service", type="service", record=True),
        ]
    )

    [billing] = result.identities
    assert billing.confidence == 0.9
    assert rules(billing) == {"same_name"}
    assert {k.key for k in billing.keys} == {
        "service:billing-api",
        "service:billing",
        "service:billing-service",
    }
    assert not any(c["attribute"] == "name" for c in billing.conflicts)


def test_an_application_named_two_ways_is_one() -> None:
    result = resolve(
        [
            seen("application:billing", PAGERDUTY, "Billing", type="application", record=True),
            seen("application:billing-platform", DATADOG, "Billing platform", type="application"),
            # A service of the same name is another kind of thing.
            seen("service:billing", DATADOG, "billing", type="service"),
        ]
    )

    application = one(result, "application:billing")
    assert {k.key for k in application.keys} == {
        "application:billing",
        "application:billing-platform",
    }
    assert rules(application) == {"same_name"}
    assert len(result.identities) == 2


def test_a_plural_and_a_team_word_are_the_same_team() -> None:
    result = resolve(
        [
            seen("team:payments-team", PAGERDUTY, "Payments Team", type="team", record=True),
            seen("team:payment", DATADOG, "payment", type="team"),
        ]
    )

    assert len(result.identities) == 1


# ── probable, not certain: linked ────────────────────────────────────────────


def test_an_environment_variant_is_linked_not_merged() -> None:
    result = resolve(
        [
            seen("service:billing", DATADOG, "billing", type="service"),
            seen("service:billing-staging", DATADOG, "billing-staging", type="service"),
        ]
    )

    assert len(result.identities) == 2
    assert links(result) == [
        ("service:billing", "service:billing-staging", "environment_variant", 0.7)
    ]


def test_a_typo_is_linked_not_merged() -> None:
    result = resolve(
        [
            seen("service:notification", DATADOG, "notification", type="service"),
            seen("service:notifcation", CUSTOM, "notifcation", type="service"),
        ]
    )

    assert [(rule, confidence) for *_, rule, confidence in links(result)] == [
        ("similar_spelling", 0.65)
    ]


# ── false positives: two things, kept two ────────────────────────────────────


def test_namesakes_with_their_own_addresses_are_never_merged() -> None:
    """Everything agrees — name, handle — but each has an address of their
    own: two people until someone says otherwise."""
    result = resolve(
        [
            seen("person:email:alex.kim@acme.io", JIRA, "Alex Kim"),
            seen("person:email:alex.kim@gmail.com", GITHUB, "Alex Kim"),
        ]
    )

    assert len(result.identities) == 2
    [(_, _, _, confidence)] = links(result)
    assert confidence == 0.89
    assert "kept apart" in result.links[0][2].evidence


def test_a_ticket_key_in_two_tools_is_ambiguous_and_names_neither() -> None:
    result = resolve(
        [
            seen(
                "acme.atlassian.net/ENG-42",
                JIRA,
                "Login fails",
                type="issue",
                aliases=("ticket:ENG-42",),
                record=True,
            ),
            seen(
                "linear.app/acme/ENG-42",
                LINEAR,
                "Dark mode",
                type="issue",
                aliases=("ticket:ENG-42",),
                record=True,
            ),
        ]
    )

    assert len(result.identities) == 2
    for identity in result.identities:
        assert rules(identity, "ambiguous") == {"ambiguous_alias"}
        assert "ticket:ENG-42" in {k.key for k in identity.keys}
        assert rules(identity) == set()


def test_an_account_seen_with_many_addresses_is_shared_not_a_person() -> None:
    result = resolve(
        [
            seen(
                f"person:email:dev{n}@acme.io",
                GITHUB,
                f"Dev {n}",
                aliases=("person:github.com:deployer",),
            )
            for n in range(6)
        ]
    )

    assert len(result.identities) == 6
    assert all(rules(i, "ambiguous") == {"shared_account"} for i in result.identities)


def test_a_bot_is_never_matched_by_its_name() -> None:
    result = resolve(
        [
            seen("person:github.com:dependabot[bot]", GITHUB, "dependabot[bot]"),
            seen("person:email:dependabot@acme.io", JIRA, "Dependabot"),
            seen("person:github.com:github-actions", GITHUB, "GitHub Actions"),
            seen("person:gitlab.com:github-actions", CUSTOM, "GitHub Actions"),
        ]
    )

    assert len(result.identities) == 4
    assert result.links == []


@pytest.mark.parametrize(
    ("key", "name", "bot"),
    [
        # What signs GitHub's merges, and an assistant's co-authored commits.
        ("person:email:noreply@github.com", "GitHub", True),
        ("person:github.com:web-flow", "GitHub", True),
        ("person:email:noreply@anthropic.com", "Claude", True),
        ("person:email:no-reply@acme.io", "Acme", True),
        # A person's private address on GitHub is a person's.
        ("person:email:12345+sara@users.noreply.github.com", "Sara Martin", False),
        ("person:github.com:sara", "Sara Martin", False),
        ("person:email:noreplyanna@acme.io", "Anna Noreply", False),
    ],
)
def test_a_services_no_reply_address_is_a_bot(key: str, name: str, bot: bool) -> None:
    assert sig.is_bot(key, name) is bot


def test_a_no_reply_address_is_never_matched_by_its_name() -> None:
    result = resolve(
        [
            seen("person:email:noreply@github.com", GITHUB, "GitHub"),
            seen("person:email:noreply@acme.io", JIRA, "GitHub"),
        ]
    )

    assert len(result.identities) == 2
    assert result.links == []


@pytest.mark.parametrize("handle", ["admin", "dev", "bob"])
def test_a_generic_or_short_handle_says_nothing(handle: str) -> None:
    result = resolve(
        [
            seen(f"person:github.com:{handle}", GITHUB, handle),
            seen(f"person:email:{handle}@acme.io", JIRA, handle),
        ]
    )

    assert (len(result.identities), result.links) == (2, [])


def test_a_crowd_of_namesakes_says_nothing() -> None:
    result = resolve([seen(f"person:github.com:user{n}x", GITHUB, "John Smith") for n in range(6)])

    assert (len(result.identities), result.links) == (6, [])


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("payment-api", "payout-api"),
        ("payment-v1", "payment-v2"),
        ("billing-backend", "billing-frontend"),
        ("api-gateway", "gateway"),
    ],
)
def test_services_that_only_look_alike_are_two(left: str, right: str) -> None:
    result = resolve(
        [
            seen(f"service:{left}", DATADOG, left, type="service"),
            seen(f"service:{right}", DATADOG, right, type="service"),
        ]
    )

    assert (len(result.identities), result.links) == (2, [])


def test_a_match_tied_between_two_that_are_not_one_another_is_no_merge() -> None:
    """A login matches two people each with an address of their own:
    merging it with either would be a guess."""
    result = resolve(
        [
            seen("person:github.com:sara-martin", GITHUB, "Sara Martin"),
            seen("person:email:sara.martin@acme.io", JIRA, "Sara Martin"),
            seen("person:email:sara.martin@other.io", CUSTOM, "Sara Martin"),
        ]
    )

    assert len(result.identities) == 3
    login = one(result, "person:github.com:sara-martin")
    assert rules(login, "ambiguous") == {"tied_match"}
    assert all(d.kind == "link" for *_, d in result.links)


def test_different_kinds_of_things_are_never_one() -> None:
    result = resolve(
        [
            seen("service:billing", DATADOG, "billing", type="service"),
            seen("team:billing", DATADOG, "billing", type="team"),
            seen("github.com/acme/billing", GITHUB, "acme/billing", type="repository", record=True),
        ]
    )

    assert (len(result.identities), result.links) == (3, [])


# ── what the sources disagree on is kept ─────────────────────────────────────


def test_a_value_the_sources_disagree_on_is_chosen_and_every_value_kept() -> None:
    result = resolve(
        [
            seen(
                "acme.atlassian.net/PAY-42",
                JIRA,
                "Refunds are doubled",
                type="issue",
                record=True,
                ago=48,
                state="open",
                priority="high",
            ),
            seen(
                "acme.atlassian.net/PAY-42",
                CUSTOM,
                "Refunds are doubled",
                type="issue",
                record=True,
                ago=1,
                state="closed",
                priority="high",
                url="https://acme.atlassian.net/browse/PAY-42",
            ),
        ]
    )

    [issue] = result.identities
    assert issue.attributes == {"state": "closed", "priority": "high"}
    [conflict] = issue.conflicts
    assert conflict["attribute"] == "state"
    assert conflict["chosen"] == "closed"  # the most recent
    assert [(v["value"], v["source_id"]) for v in conflict["values"]] == [  # type: ignore[attr-defined]
        ("closed", str(CUSTOM)),
        ("open", str(JIRA)),
    ]


def test_two_names_for_one_address_are_a_conflict_a_longer_one_is_not() -> None:
    renamed = resolve(
        [
            seen("person:email:s.m@acme.io", GITHUB, "Sara Martin", ago=10),
            seen("person:email:s.m@acme.io", JIRA, "Sarah Johnson", ago=1),
        ]
    )
    married = resolve(
        [
            seen("person:email:s.m@acme.io", GITHUB, "Sara Martin", ago=10),
            seen("person:email:s.m@acme.io", JIRA, "Sara Martin-Dupont", ago=1),
        ]
    )

    [person] = renamed.identities
    [conflict] = person.conflicts
    assert (conflict["attribute"], conflict["chosen"]) == ("name", "Sarah Johnson")
    assert {v["value"] for v in conflict["values"]} == {"Sara Martin", "Sarah Johnson"}  # type: ignore[attr-defined]
    [person] = married.identities
    assert person.conflicts == []
    assert person.names == ["Sara Martin-Dupont", "Sara Martin"]


def test_a_handle_is_not_a_name_to_disagree_with() -> None:
    result = resolve(
        [
            seen(
                "person:email:sara@acme.io",
                GITHUB,
                "Sara Martin",
                aliases=("person:github.com:sara",),
            ),
            seen("person:github.com:sara", GITHUB, "sara"),
        ]
    )

    [sara] = result.identities
    assert (sara.name, sara.conflicts) == ("Sara Martin", [])


# ── a workspace, as it comes ─────────────────────────────────────────────────


def test_a_workspace_of_five_tools_resolves_to_what_it_holds() -> None:
    result = resolve(
        [
            # GitHub: a commit's author by address, a pull request's by login.
            seen(
                "person:email:sara@acme.io",
                GITHUB,
                "Sara Martin",
                aliases=("person:github.com:sara",),
            ),
            seen("person:github.com:sara", GITHUB, "sara"),
            seen("person:email:12345+omar@users.noreply.github.com", GITHUB, "Omar"),
            seen("person:github.com:omar", GITHUB, "omar"),
            seen("person:github.com:dependabot[bot]", GITHUB, "dependabot[bot]"),
            # Jira: the same Sara by a plus address; a ticket.
            seen("person:email:sara+jira@acme.io", JIRA, "Sara Martin"),
            seen(
                "acme.atlassian.net/PAY-42",
                JIRA,
                "Refunds are doubled",
                type="issue",
                aliases=("ticket:PAY-42",),
                record=True,
            ),
            # PagerDuty and Datadog: one service, two ways; its team.
            seen("service:billing-api", PAGERDUTY, "Billing API", type="service", record=True),
            seen("service:billing", DATADOG, "billing", type="service"),
            seen("team:payments-team", PAGERDUTY, "Payments Team", type="team", record=True),
            seen("team:payments", DATADOG, "payments", type="team"),
        ]
    )

    assert sorted((i.type, i.key) for i in result.identities) == [
        ("issue", "acme.atlassian.net/PAY-42"),
        ("person", "person:email:sara@acme.io"),
        ("person", "person:github.com:dependabot[bot]"),
        ("person", "person:github.com:omar"),
        ("service", "service:billing-api"),
        ("team", "team:payments-team"),
    ]
    assert result.links == []
    assert one(result, "person:email:sara+jira@acme.io").sources == sorted([GITHUB, JIRA], key=str)


def test_the_same_input_resolves_the_same_way() -> None:
    mentions = [
        seen("service:billing-api", PAGERDUTY, "Billing API", type="service", record=True),
        seen("service:billing", DATADOG, "billing", type="service"),
        seen("person:email:sara@acme.io", GITHUB, "Sara Martin"),
    ]

    first, second = resolve(mentions), resolve(list(reversed(mentions)))

    assert sorted(i.key for i in first.identities) == sorted(i.key for i in second.identities)
