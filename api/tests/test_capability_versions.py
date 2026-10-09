"""LEKA's own capabilities, each version what it was when registered.

The catalogue keeps the fingerprint of every version it registered and
refuses the same version said otherwise (`changed_without_version`,
LEKA-393): in production the capability shows « Refusée » in Capacités and
can no longer be routed to. That happened once: `incidents` gained a goal and
a kind without a new version (2026-10-09). Nothing caught it before
production; this does.

Changed a capability's goals, kinds, summary, examples, what it needs? Give
it a new version (intentions/capabilities.py), then its new line here. A
line is never edited for the same version.
"""

from __future__ import annotations

from leka.intentions.capabilities import definitions

# key: (version, fingerprint) — as registered.
REGISTERED: dict[str, tuple[str, str]] = {
    "standing": ("1.0.0", "cb9c370be20abe7d7e38908916b74567a865bb53dace87dbeb9c88949acd3df2"),
    "ownership": ("1.0.0", "0ce6651c7f538b22ac48a35cba2378e65a2d4b9737e41354819d2b5dce85391a"),
    "dependencies": ("1.0.0", "64117ddc599a1f0442f66862246518b829516ed9ee850b5603c0ac21bdaaf1ab"),
    "incidents": ("2.0.0", "94c1a8205f5852331f2d8a95d6391d1b0e41a28e634040d398a8ca5f0841bcb1"),
    "changes": ("1.0.0", "f557cbdfd5f2ea37824b70b547b457ff18a2b8a4fcd7638c3eae97387ce61909"),
    "evolution": ("1.0.0", "e56f06eaa1e939463e3474f114bb48a3813b76c1090e450a25d92156eff5c986"),
    "documentation": ("1.0.0", "01691b9be1e8f4f70697362e62109f3f75d8ef94585f84ee0563c67134658591"),
    "compliance": ("1.0.0", "0b0a7df078c0c5dd2f271e2ef347f95b6955dc0d88d84d438c8574c019f4124b"),
    "migration": ("1.0.0", "93788808f1805706b55da2cc1fef8115991e93b90eb29b67a6e56b740866f077"),
    "action": ("1.0.0", "43d5657d146998560904f857840c9e5aa4fa47cb49a74da6eb2c059a8e37a6ba"),
    "synthesis": ("1.0.0", "b8500f2c32ed0e80eb4878fda6491af4fad6bf942105945bdef39387cc142a49"),
}


def test_a_capability_changed_takes_a_new_version() -> None:
    changed = [
        f"{d.key} {d.version}"
        for d in definitions()
        if d.key in REGISTERED
        and REGISTERED[d.key][0] == d.version
        and REGISTERED[d.key][1] != d.fingerprint()
    ]
    assert not changed, (
        f"changed without a new version: {changed} — the catalogue refuses it in production "
        "(changed_without_version). Give it a new version, then its new line in REGISTERED."
    )


def test_every_capability_is_locked() -> None:
    """A new capability, or a new version, comes with its line."""
    unlocked = [
        f"{d.key} {d.version}"
        for d in definitions()
        if REGISTERED.get(d.key, ("", ""))[0] != d.version
    ]
    assert not unlocked, f"add to REGISTERED: {unlocked}"
