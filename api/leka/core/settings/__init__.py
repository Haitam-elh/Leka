"""Settings, one file per domain.

`leka.core.config` assembles these into the single `Settings` class and the
single `settings` instance. Nothing imports from here directly — the public
path is still `from leka.core.config import settings`, unchanged for the
seventeen modules that use it.

WHY THIS IS SPLIT AT ALL. The settings file is the one place every ticket
eventually touches: a new connector wants credentials, a queue wants a
timeout, a sweep wants a retention. When two people work at once, they
collide there and nowhere else — guaranteed, because the file grows with
every feature and belongs to no feature.

So a domain owns a file. Adding one is: write `core/settings/<domain>.py`,
then two lines in `core/config.py` — an import and a name in the base list.
The person adding it never edits anyone else's fields, and the diff a
reviewer reads is the domain, not a patch in the middle of four hundred
lines.

WHAT THIS DELIBERATELY IS NOT. Not nested models. pydantic-settings would
then expect `LEKA_QUEUE__MAX_ATTEMPTS`, with a double underscore, and the
flat `LEKA_*` naming is a contract: it is what `.env.example` documents,
what CI sets, and what an operator types. Mixins keep the names flat and
still give each domain its own file.

WHAT LIVES WHERE

    paths.py        REPO_ROOT, so several domains can resolve relative paths
    runtime.py      environment, logging, CORS, the API prefix
    database.py     PostgreSQL and Redis connections, the pool
    security.py     signing and encryption keys, sessions, cookies
    storage.py      object store, S3, retention
    email.py        SMTP and the API sender
    model_access.py the LLM provider and its keys
    credits.py      the plans' AI credits, warnings, the limit enforced
    _rotation.py    RotateEvery, the lifetime each secret field declares

A field validator lives with the field it validates. A validator that spans
domains — "in production, the cookie must be Secure" combines `environment`
with a cookie field — lives in `core/config.py`, because it belongs to the
assembly and not to either domain.

ONE TRAP, AND IT IS SILENT. **Method names must be unique across domains.**
Python resolves them by MRO, so two mixins defining `_blank_is_not_configured`
leave exactly one alive and the other's fields simply stop being validated —
no error, no warning, and pydantic reports nothing. That happened while this
split was being written: three domains used the same validator name, only
the email one survived, and blank S3 and model keys silently went back to
being `""`.

Prefix a validator with its domain: `_blank_s3_field_is_not_configured`,
not `_blank_is_not_configured`. `test_config.py` has a check that fails if
two domains ever share a name again.
"""

from leka.core.settings._rotation import RotateEvery
from leka.core.settings.database import DatabaseSettings
from leka.core.settings.email import EmailSettings
from leka.core.settings.model_access import ModelAccessSettings
from leka.core.settings.paths import REPO_ROOT
from leka.core.settings.runtime import RuntimeSettings
from leka.core.settings.security import SecuritySettings
from leka.core.settings.storage import StorageSettings

__all__ = [
    "REPO_ROOT",
    "DatabaseSettings",
    "EmailSettings",
    "ModelAccessSettings",
    "RotateEvery",
    "RuntimeSettings",
    "SecuritySettings",
    "StorageSettings",
]
