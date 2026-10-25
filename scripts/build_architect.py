"""The downloadable architect, built on disk (2026-10-25): the very zip LEKA
hands out to an organisation the agent is dedicated to — LEKA's own code
(api/leka/architect), renamed leka_architect, its README, .env.example,
Dockerfile, MCP configurations and prompt pack.

    python scripts/build_architect.py                 # dist/leka-architect-<version>.zip
    python scripts/build_architect.py --output /tmp   # elsewhere
    python scripts/build_architect.py --unpacked      # and unpacked beside it

Then, to try it:

    pip install ./dist/leka-architect
    leka-architect --help
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from leka.architect import package  # noqa: E402 - the API's own code, found above


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default=str(ROOT / "dist"))
    parser.add_argument("--unpacked", action="store_true", help="unpack it beside the zip")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    built = package.build_zip()
    target = out / package.file_name()
    target.write_bytes(built)
    print(target)
    if args.unpacked:
        with zipfile.ZipFile(io.BytesIO(built)) as zipped:
            zipped.extractall(out)
        print(out / package.ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
