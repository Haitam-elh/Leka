"""Re-encrypt every stored secret under the first key of LEKA_ENCRYPTION_KEYS:
the sources' credentials, then the signing secrets of the systems a workspace
authorized LEKA to act through (LEKA-391), then the keys of the workspaces'
own language models (LEKA-394).

    api/.venv/bin/python scripts/rotate_encryption_key.py --dry-run
    api/.venv/bin/python scripts/rotate_encryption_key.py

Step three of five, and the order is the procedure:

  1. put the NEW key first in LEKA_ENCRYPTION_KEYS, keep the old one after it
  2. deploy — every new write now uses the new key
  3. run this, --dry-run first
  4. run it again: it must report 0 rotated and 0 unreadable
  5. remove the old key, in a LATER deploy

Removing the old key before step 3 has finished leaves rows nobody can read.
Skipping step 2 means the API keeps writing under the old key while this
runs. Interrupting step 3 costs nothing: run it again. Why, and what happens
to a credential saved meanwhile, is in leka/connectors/tasks.py (and
leka/intentions/tasks.py for the signing secrets, leka/capabilities/tasks.py
for the model keys).

Unlike seed.py, this runs against production, by hand.

Exit status: 0 done; 1 some secrets no configured key can read (each is
logged with its id, and nothing else was held back); 2 refused.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from leka.capabilities.tasks import rotate_model_keys
from leka.connectors import RotationRefusedError, RotationReport, rotate_source_credentials
from leka.core.config import settings
from leka.core.logging import configure_logging
from leka.intentions.tasks import rotate_endpoint_secrets
from leka.platform import secret_box


def _said(what: str, report: RotationReport, *, dry_run: bool) -> str:
    verb = "would be rotated" if dry_run else "rotated"
    return (
        f"{what}: {report.examined} examined: {report.rotated} {verb}, "
        f"{report.current} already under the new key, "
        f"{report.changed} changed during the run and left alone, "
        f"{report.unreadable} unreadable"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-encrypt stored credentials.")
    parser.add_argument("--dry-run", action="store_true", help="count, write nothing")
    parser.add_argument("--batch-size", type=int, default=500, help="rows per transaction")
    arguments = parser.parse_args()

    configure_logging(settings)
    batch, dry_run = arguments.batch_size, arguments.dry_run
    try:
        credentials = asyncio.run(
            rotate_source_credentials(secret_box, batch=batch, dry_run=dry_run)
        )
        signing = asyncio.run(rotate_endpoint_secrets(secret_box, batch=batch, dry_run=dry_run))
        models = asyncio.run(rotate_model_keys(secret_box, batch=batch, dry_run=dry_run))
    except RotationRefusedError as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2

    print(_said("credentials", credentials, dry_run=dry_run))
    print(_said("signing secrets", signing, dry_run=dry_run))
    print(_said("model keys", models, dry_run=dry_run))
    return 1 if credentials.unreadable or signing.unreadable or models.unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
