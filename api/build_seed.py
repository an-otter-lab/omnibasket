"""Where the demo pages come from, and why this module no longer builds them.

``data/cache/ro-v1-seed.json`` is the source of the demo pages. Each row holds
the facts a read produced (title, ISBN, price in cents, currency, availability,
seller, and the shop's own delivery lines) plus the Muse Spark read stored for
that page. The raw page text, the capture folders it was read from, and the
exploration scripts that produced them are not part of this repository, so the
seed cannot be rebuilt from a checkout: it is edited in place, or regenerated
from captures that live outside the repo.

The seed is loaded by ``api.cache.load_seed`` and read by the app through
``PageCache``. Nothing in the runtime reads a page's text.
"""

from __future__ import annotations

SEED = "data/cache/ro-v1-seed.json"


def build() -> dict:
    """Refuse: there is no capture folder in this repository to build from."""

    raise SystemExit(
        "the demo seed is the source now: it is not rebuilt from this checkout. "
        f"Edit {SEED} directly, or regenerate it from captures kept outside the repo."
    )


def main() -> None:
    build()


if __name__ == "__main__":
    main()
