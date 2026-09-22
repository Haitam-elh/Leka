"""An empty string is not a value.

`.env.example` ships optional variables present but blank, so copying it
yields `""` rather than an absent variable. Without this, a setting nobody
filled in reads as configured, and the failure moves from startup to the
first time it is used — which is the failure mode the whole settings module
exists to prevent.

Found the hard way on LEKA-332: with `LEKA_S3_BUCKET` blank,
`LEKA_OBJECT_STORE=s3` in production passed the startup guard — which tested
each value against None — and the process started with a bucket called "".
The first payload write would have been the first sign.

One function rather than one copy per domain, so a domain added later gets
the behaviour by calling it rather than by remembering it.
"""

from __future__ import annotations


def blank_is_none(value: object) -> object:
    """Turn a blank or whitespace-only string into None. Leave the rest."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


__all__ = ["blank_is_none"]
