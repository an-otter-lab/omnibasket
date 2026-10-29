"""Seed the SQLite page cache from data/cache/ro-v1-seed.json.

Safe to run more than once. An existing cache is kept unless the seed file is
newer than it, which happens after a pull that changes the pages; then the
cache is reseeded so the demo shows the seed's reads, not older ones.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app import DEFAULT_DB
from api.cache import SEED_PATH, load_seed, open_seeded


def main() -> None:
    cache = open_seeded(DEFAULT_DB)
    stale = (
        cache.count() > 0
        and SEED_PATH.exists()
        and DEFAULT_DB.exists()
        and SEED_PATH.stat().st_mtime > DEFAULT_DB.stat().st_mtime
    )
    if stale:
        load_seed(cache)
        print(f"page cache {DEFAULT_DB} reseeded rows={cache.count()}")
        return
    print(f"page cache {DEFAULT_DB} rows={cache.count()}")


if __name__ == "__main__":
    main()
