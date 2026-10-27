"""Build data/cache/ro-v1-seed.json from the saved spike captures.

Looks in this worktree first, then the sibling worktrees that hold the
28 Oct reads. Does not open a network connection.
"""

from __future__ import annotations

import json
from pathlib import Path

from api.basket import ROOT, load_locked

SEARCH_ROOTS = [
    ROOT,
    ROOT.parent / "omnibasket-libris",
    ROOT.parent / "omnibasket-point3",
    ROOT.parent / "omnibasket-basket-complete",
    ROOT.parent / "omnibasket",
]


def _find(relative: str) -> Path | None:
    for root in SEARCH_ROOTS:
        candidate = root / relative
        if candidate.is_file() or candidate.is_dir():
            return candidate
    return None


def _source_label(folder: Path) -> str:
    for root in SEARCH_ROOTS:
        try:
            folder.relative_to(root)
        except ValueError:
            continue
        return root.name
    return "capture"


def _capture_dir(relative_file: str) -> Path | None:
    # Basket paths point at text.txt inside the capture directory.
    direct = _find(relative_file)
    if direct is not None and direct.is_file():
        return direct.parent
    parent = _find(str(Path(relative_file).parent))
    if parent is not None and parent.is_dir():
        return parent
    return None


def build() -> dict:
    _day, _currency, _stores, _items, pages = load_locked()
    rows = []
    missing = []
    for page in pages:
        folder = _capture_dir(page["capture"])
        if folder is None:
            missing.append(page["capture"])
            continue
        text_path = folder / "text.txt"
        if not text_path.is_file():
            missing.append(page["capture"])
            continue
        screenshot = None
        for name in ("screenshot_top.png", "screenshot.png"):
            if (folder / name).is_file():
                screenshot = str(Path(page["capture"]).parent / name)
                break
        model = None
        model_path = next(folder.glob("model_*.json"), None)
        if model_path is not None:
            model = json.loads(model_path.read_text())
        meta_path = folder / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.is_file() else None
        rows.append(
            {
                "store_id": page["store_id"],
                "isbn13": page["isbn13"],
                "item_id": page["item_id"],
                "day": page["day"],
                "page_text": text_path.read_text(),
                "screenshot_path": screenshot,
                "model_json": model,
                "provenance": {
                    "capture": page["capture"],
                    "resolved_from": _source_label(folder) + "/" + page["capture"],
                    "meta": meta,
                    "seeded_from": "spike/out",
                },
            }
        )
    if missing:
        raise SystemExit("missing captures: " + ", ".join(missing))
    return {"day": "2026-10-28", "currency": "RON", "pages": rows}


def main() -> None:
    payload = build()
    out = ROOT / "data" / "cache" / "ro-v1-seed.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {out} pages={len(payload['pages'])}")


if __name__ == "__main__":
    main()
