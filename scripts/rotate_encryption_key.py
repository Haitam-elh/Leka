"""Re-encrypt every stored credential under the first key of LEKA_ENCRYPTION_KEYS.

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
to a credential saved meanwhile, is in leka/connectors/tasks.py.

Unlike seed.py, this runs against production, by hand.

Exit status: 0 done; 1 some credentials no configured key can read (each is
logged with its source id, and nothing else was held back); 2 refused.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from leka.connectors import RotationRefusedError, rotate_source_credentials
from leka.core.config import settings
from leka.core.logging import configure_logging
from leka.platform import secret_box


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-encrypt stored credentials.")
    parser.add_argument("--dry-run", action="store_true", help="count, write nothing")
    parser.add_argument("--batch-size", type=int, default=500, help="rows per transaction")
    arguments = parser.parse_args()

    configure_logging(settings)
    try:
        report = asyncio.run(
            rotate_source_credentials(
                secret_box, batch=arguments.batch_size, dry_run=arguments.dry_run
            )
        )
    except RotationRefusedError as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2

    verb = "would be rotated" if arguments.dry_run else "rotated"
    print(
        f"{report.examined} examined: {report.rotated} {verb}, "
        f"{report.current} already under the new key, "
        f"{report.changed} changed during the run and left alone, "
        f"{report.unreadable} unreadable"
    )
    return 1 if report.unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
