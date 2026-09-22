"""Where raw payloads go, and how long they stay.

The bytes do not live in PostgreSQL — see docs/adr/010-object-storage.md.
These settings say which store holds them and what the ceilings are.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator

from leka.core.settings._blank import blank_is_none
from leka.core.settings._rotation import RotateEvery
from leka.core.settings.paths import REPO_ROOT


class StorageSettings:
    """Object store, S3 credentials, size ceiling, retention overrides."""

    # "local" is the default so the whole platform is testable with no
    # account anywhere, exactly as the console email sender did for
    # LEKA-330. Production refuses to start with it — the check is in
    # core/config.py, because it combines this with `environment`.
    object_store: Literal["local", "s3"] = "local"

    # Where LocalObjectStore writes. Relative paths resolve against the repo
    # root, so one developer's working directory is not part of the contract.
    object_store_path: Path = Path("var/objects")

    # S3-compatible. Cloudflare R2, Amazon S3, MinIO — same protocol and the
    # same code either way: only the endpoint changes.
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    # R2 ignores the region and wants "auto"; S3 wants a real one.
    s3_region: str = "auto"
    s3_access_key_id: str | None = None
    s3_secret_access_key: Annotated[SecretStr | None, RotateEvery(days=90)] = None

    # The largest single payload LEKA will store, in bytes. Default 1 GiB.
    #
    # Streaming bounds our MEMORY; it does not bound the disk, the bill, or
    # the time a sync takes. A source that answers with forty gigabytes has
    # either broken or been asked the wrong question, and storing it is the
    # expensive way to find out. The write is refused mid-flight, before the
    # bytes land, and nothing is left behind.
    #
    # A ceiling, not a target. Raise it when a real payload is refused, and
    # look at the payload first.
    max_object_bytes: int = Field(default=1024 * 1024 * 1024, ge=1024 * 1024)

    # How long a raw payload is ours to keep, in days, per source kind. The
    # policy itself lives in leka.ingestion.retention, which is where the
    # source vocabulary belongs; this is only the override, so a customer
    # contract or a regulator can move a number without a deploy.
    #
    #   LEKA_RAW_PAYLOAD_RETENTION_DAYS={"datadog": 14, "github": 180}
    raw_payload_retention_days: dict[str, int] = Field(default_factory=dict)

    @field_validator(
        "s3_bucket",
        "s3_endpoint_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        mode="before",
    )
    @classmethod
    def _blank_s3_field_is_not_configured(cls, value: object) -> object:
        """A blank bucket name is not a bucket. See core/settings/_blank.py."""
        return blank_is_none(value)

    @field_validator("raw_payload_retention_days")
    @classmethod
    def _retention_is_within_reason(cls, value: dict[str, int]) -> dict[str, int]:
        """Refuse a retention that is obviously wrong, at startup.

        0 deletes a payload the moment it lands, which reads as "disabled"
        to whoever typed it and means "delete everything" to the sweep. A
        number in the thousands is a typo nobody notices until the storage
        bill does. Both must stop the process, not the sweep.
        """
        for kind, days in value.items():
            if not 1 <= days <= 3650:
                msg = (
                    f"LEKA_RAW_PAYLOAD_RETENTION_DAYS[{kind!r}] is {days}. "
                    "Retention is in DAYS and must be between 1 and 3650."
                )
                raise ValueError(msg)
        return value

    @property
    def object_store_root(self) -> Path:
        """Where LocalObjectStore writes, as an absolute path.

        A relative setting resolves against the repository root rather than
        the process working directory: the API, the worker and a test runner
        start from different places and must agree on one directory.
        """
        configured = self.object_store_path
        return configured if configured.is_absolute() else REPO_ROOT / configured


__all__ = ["StorageSettings"]
