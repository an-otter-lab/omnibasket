#!/usr/bin/env python3
"""Purge stale negative cache entries from older matcher versions.

Run this on the live checkout to clean up old negative entries that were
cached before the matcher version was added to the cache key.

Usage:
    python scripts/purge_stale_negatives.py [cache_path]

If cache_path is not provided, uses the default location.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import api modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.cache import PageCache
from api.title_match import MATCHER_VERSION


def main():
    if len(sys.argv) > 1:
        cache_path = Path(sys.argv[1])
    else:
        # Default cache location
        cache_path = Path("data/cache/page_cache.sqlite")
    
    if not cache_path.exists():
        print(f"Cache file not found: {cache_path}")
        sys.exit(1)
    
    print(f"Opening cache: {cache_path}")
    cache = PageCache(cache_path)
    
    # The __init__ already calls purge_old_negatives automatically
    # But let's run it explicitly here to show the count
    deleted = cache.purge_old_negatives(MATCHER_VERSION)
    
    print(f"Purged {deleted} stale negative entries from older matcher versions")
    print(f"Current matcher version: {MATCHER_VERSION}")


if __name__ == "__main__":
    main()
