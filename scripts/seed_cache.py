"""Seed the SQLite page cache from data/cache/ro-v1-seed.json.

Safe to run more than once: an existing cache is left as it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app import DEFAULT_DB
from api.cache import open_seeded


def main() -> None:
    cache = open_seeded(DEFAULT_DB)
    print(f"page cache {DEFAULT_DB} rows={cache.count()}")


if __name__ == "__main__":
    main()
