"""FastAPI routes for health, cache-only solve, and page-read events."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.basket import excluded_for_unresolved_fees, load_locked, locked_shop_rows
from api.cache import PageCache, open_seeded
from api.memberships import apply_memberships, check_declared, load_profiles, memberships_payload
from api.rate_limit import DailyPasteLimiter, PerIPRateLimitMiddleware
from api.solve_service import (
    context_from_body,
    context_from_locked,
    items_from_body,
    solution_payload,
    stores_from_body,
)
from solver.optimize import SolverError
from solver.types import Item

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "cache" / "ro-v1.sqlite"
UI_DIST = ROOT / "ui" / "dist" / "ui" / "browser"


class OfferIn(BaseModel):
    store_id: str
    price_cents: int
    seller_certainty: str
    edition: str | None = None
    listing_url: str | None = None
    read_at: str | None = None
    in_stock: bool | None = None


class ItemIn(BaseModel):
    id: str
    title: str | None = None
    isbn13: str | None = None
    offers: list[OfferIn]


class StoreIn(BaseModel):
    id: str
    currency: str
    free_shipping_threshold_cents: int
    shipping_fee_cents: int | None = None
    per_order_fee_cents: int
    read_at: str | None = None


class InputIn(BaseModel):
    raw_input: str = Field(default="", max_length=2000)


class WhyIn(BaseModel):
    """The /solve payload and the shopper's language (ro or en)."""

    payload: dict
    lang: str = Field(default="en")


class AskStateIn(BaseModel):
    """What the UI already holds; every list is capped so a hostile body stays small."""

    tab: Literal["cheapest", "one", "custom"] = "cheapest"
    selected_store_ids: list[str] | None = Field(default=None, max_length=20)
    memberships: list[str] = Field(default_factory=list, max_length=20)
    edition_pins: dict[str, str] = Field(default_factory=dict)
    store_ids: list[str] = Field(default_factory=list, max_length=20)
    membership_ids: list[str] = Field(default_factory=list, max_length=20)
    items: list[dict] = Field(default_factory=list, max_length=50)


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    lang: Literal["en", "ro"]
    state: AskStateIn


class SolveIn(BaseModel):
    stores: list[StoreIn] | None = None
    items: list[ItemIn] | None = None
    source: str = Field(default="cache")
    require_romanian_store: bool = False
    # Custom tab: the shops the shopper chose. Each must take a book.
    selected_store_ids: list[str] | None = None
    # Exact edition: {item_id: edition}. A missing book or "any" means any edition.
    edition_pins: dict[str, str] | None = None
    # Feature 5: memberships the shopper declares, by id from data/shops.
    memberships: list[str] | None = None


def demo_enabled() -> bool:
    """Demo mode is on only when OMNIBASKET_DEMO says 1/true. Anything else is normal mode."""
    return os.environ.get("OMNIBASKET_DEMO", "").strip().lower() in {"1", "true"}


def _commit_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=2
        )
        return (out.stdout.strip() or None) if out.returncode == 0 else None
    except Exception:
        return None


def _require_demo(app: FastAPI) -> None:
    """Captured sample data is served in demo mode only; normal mode answers 404."""
    if not app.state.demo:
        raise HTTPException(status_code=404, detail="Not found")


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Omnibasket", version="v1")
    app.add_middleware(PerIPRateLimitMiddleware)
    path = db_path or DEFAULT_DB
    app.state.db_path = path
    from index.search import DB as INDEX_DB
    app.state.index_db_path = INDEX_DB
    app.state.paste_limiter = DailyPasteLimiter()
    app.state.demo = demo_enabled()
    app.state.commit = _commit_sha()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/config")
    def config_route() -> dict:
        return {"demo": app.state.demo, "commit": app.state.commit}

    @app.get("/sample")
    def sample_route() -> JSONResponse:
        """The ro-v1 sample basket ('Try a sample basket'). Demo mode only."""
        _require_demo(app)
        try:
            _pages, payload = _cached_solution(app, "cache")
        except SolverError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        return JSONResponse(payload)

    @app.get("/search")
    def search_route(q: str = Query(default=""), limit: int = Query(default=10, ge=1, le=100)):
        from index.search import SearchUnavailable, search

        try:
            results = search(q, limit=limit, db_path=app.state.index_db_path)
        except SearchUnavailable:
            return JSONResponse({"query": q, "results": [], "error": "search_unavailable"}, status_code=503)
        return {"query": q, "results": results}

    @app.post("/photo")
    async def photo_route(request: Request) -> JSONResponse:
        """Raw image body (png/jpeg/webp). Read in memory, never stored or logged."""
        from api import photo_read

        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype not in photo_read.ALLOWED_TYPES:
            return JSONResponse(status_code=415, content={"error": "unsupported_type", "allowed": sorted(photo_read.ALLOWED_TYPES)})
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > photo_read.MAX_IMAGE_BYTES:
            return JSONResponse(status_code=413, content={"error": "too_large", "max_bytes": photo_read.MAX_IMAGE_BYTES})
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > photo_read.MAX_IMAGE_BYTES:
                return JSONResponse(status_code=413, content={"error": "too_large", "max_bytes": photo_read.MAX_IMAGE_BYTES})
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            return JSONResponse(status_code=400, content={"error": "empty_body"})
        if photo_read.sniff_type(data) != ctype:
            return JSONResponse(status_code=415, content={"error": "unsupported_type", "allowed": sorted(photo_read.ALLOWED_TYPES)})
        result = await run_in_threadpool(photo_read.read_and_match, data, ctype, app.state.index_db_path)
        return JSONResponse(result)

    @app.post("/input")
    def input_route(body: InputIn, request: Request) -> JSONResponse:
        from api import input_understanding as iu

        ip = request.client.host if request.client else "unknown"
        try:
            result = iu.understand(
                body.raw_input,
                ip=ip,
                limiter=app.state.paste_limiter,
                index_db=app.state.index_db_path,
            )
        except iu.LimitTripped as exc:
            return JSONResponse(
                status_code=429,
                content={"error": exc.reason, "message": "Too many pasted links today. Try again tomorrow."},
                headers={"Retry-After": "86400"},
            )
        return JSONResponse(result)

    @app.post("/solve")
    def solve_route(
        body: SolveIn | None = None,
        source: str = Query(default="cache"),
        require_romanian_store: bool = Query(default=False),
    ) -> JSONResponse:
        mode = body.source if body and body.source else source
        forced = require_romanian_store or bool(body and body.require_romanian_store)
        try:
            payload = _solve(app, body, mode, require_romanian_store=forced)
        except SolverError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        return JSONResponse(payload)

    @app.post("/why")
    def why_route(body: WhyIn) -> JSONResponse:
        from api.why import explain

        public = explain(body.payload, body.lang)
        public.pop("reason", None)
        return JSONResponse(public)

    @app.post("/ask")
    def ask_route(body: AskIn) -> JSONResponse:
        """Ask Omnibasket: keys and ids only, never prose. Always 200 (429 comes from the shared limiter)."""
        from api import ask

        result = ask.answer(body.text, body.lang, body.state.model_dump())
        return JSONResponse(result.as_response())

    @app.get("/events")
    async def events(
        source: str = Query(default="cache"),
        isbn13: str | None = Query(default=None),
        item_id: str | None = Query(default=None),
        title: str | None = Query(default=None),
        author: str | None = Query(default=None),
        stores: str | None = Query(default=None, description="comma list of shop ids; default is every indexed shop"),
        listing: str | None = Query(default=None, description="a pasted shop page to read instead of the index entry"),
    ):
        if source == "live":
            from api.offers import default_live_stores, valid_live_stores
            from matching.isbn import normalize_isbn13

            isbn = normalize_isbn13(isbn13)
            if isbn is None:
                return JSONResponse(
                    status_code=400,
                    content={"error": "isbn13 is required and must be a valid ISBN-13 (check digit)"},
                )
            chosen = [s.strip() for s in stores.split(",") if s.strip()] if stores else default_live_stores()
            bad = [s for s in chosen if s not in valid_live_stores()]
            if bad or not chosen:
                return JSONResponse(status_code=400, content={"error": "unknown shops: " + ", ".join(bad or ["(none)"])})
            listing_urls = None
            if listing:
                from api.input_understanding import indexed_shop_for

                pasted = indexed_shop_for(listing)
                if pasted is None:
                    return JSONResponse(status_code=400, content={"error": "listing is not a shop page"})
                if pasted.id in chosen:
                    listing_urls = {pasted.id: listing}
            book_id = (item_id or "").strip() or "book-" + isbn
            book_title = (title or "").strip() or book_id

            async def generate_live():
                from api.offers import read_offers_parallel, solve_with_live_offers, ReadProgress
                import asyncio

                progress_queue: asyncio.Queue[ReadProgress | None] = asyncio.Queue()

                async def progress_callback(progress: ReadProgress):
                    await progress_queue.put(progress)

                async def _run():
                    try:
                        return await read_offers_parallel(
                            chosen, isbn, book_id, _cache(app), progress_callback,
                            title=(title or None), author=(author or None),
                            listing_urls=listing_urls,
                        )
                    finally:
                        await progress_queue.put(None)

                read_task = asyncio.create_task(_run())

                while True:
                    progress = await progress_queue.get()
                    if progress is None:
                        break
                    yield _sse(
                        "read_progress",
                        {
                            "store_id": progress.store_id,
                            "isbn13": progress.isbn13,
                            "status": progress.status,
                            "message": progress.message,
                        },
                    )

                offers = await read_task
                try:
                    payload = solve_with_live_offers(offers, book_id, book_title, isbn)
                except SolverError as exc:
                    yield _sse("error", {"error": str(exc)})
                    return
                yield _sse("solution", payload)

            return StreamingResponse(generate_live(), media_type="text/event-stream")
        else:
            # Cache mode serves captured data: demo mode only.
            _require_demo(app)
            def generate():
                # Finish every cache read before the first yield. The connection
                # opened for this request is closed inside PageCache before we get here.
                try:
                    pages, payload = _cached_solution(app, source)
                except SolverError as exc:
                    payload: dict = {"error": str(exc)}
                    misses = getattr(exc, "misses", None)
                    if misses:
                        payload["misses"] = misses
                    yield _sse("error", payload)
                    return
                for page in pages:
                    yield _sse(
                        "page",
                        {
                            "store_id": page["store_id"],
                            "isbn13": page["isbn13"] or None,
                            "item_id": page["item_id"],
                            "cache": page["cache"],
                            "status": page["status"],
                        },
                    )
                yield _sse("solution", payload)
            
            return StreamingResponse(generate(), media_type="text/event-stream")

    # API routes above take precedence. The built Angular app is the demo UI.
    if UI_DIST.is_dir():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")

    return app


def _cache(app: FastAPI) -> PageCache:
    cache = getattr(app.state, "cache", None)
    if cache is None:
        cache = open_seeded(app.state.db_path)
        app.state.cache = cache
    return cache


LIVE_SOLVE_REFUSAL = (
    "POST /solve serves the cache only; a live solve runs over GET /events?source=live&isbn13=..."
)


def _refuse_live(source: str) -> None:
    if source == "live":
        raise SolverError(LIVE_SOLVE_REFUSAL)


def _solve(
    app: FastAPI,
    body: SolveIn | None,
    source: str,
    *,
    require_romanian_store: bool = False,
) -> dict:
    profiles = load_profiles()
    declared = check_declared(body.memberships if body else None, profiles)
    if body and body.stores and body.items:
        _refuse_live(source)
        if source not in {"given", "cache"}:
            raise SolverError(f"unsupported solve source {source!r}")
        # A caller-supplied basket is arithmetic only. It does not fetch pages.
        store_rows = [row.model_dump() for row in body.stores]
        item_rows = [row.model_dump() for row in body.items]
        stores = apply_memberships(stores_from_body(store_rows), declared, profiles)
        items = items_from_body(item_rows)
        excluded = _excluded_for_posted_stores(stores)
        payload = solution_payload(
            stores,
            items,
            require_romanian_store=require_romanian_store,
            excluded_stores=excluded,
            plan_ctx=context_from_body(stores, items, item_rows, store_rows, excluded),
            selected_store_ids=body.selected_store_ids,
            edition_pins=body.edition_pins,
        )
        payload["memberships"] = memberships_payload(stores, declared, profiles)
        return payload
    _require_demo(app)
    _, payload = _cached_solution(
        app,
        source,
        require_romanian_store=require_romanian_store,
        selected_store_ids=body.selected_store_ids if body else None,
        edition_pins=body.edition_pins if body else None,
        memberships=declared,
    )
    return payload


def _cached_solution(
    app: FastAPI,
    source: str,
    *,
    require_romanian_store: bool = False,
    selected_store_ids: list[str] | None = None,
    edition_pins: dict[str, str] | None = None,
    memberships: list[str] | None = None,
) -> tuple[list[dict], dict]:
    from api.solve_service import offers_from_cache

    profiles = load_profiles()
    declared = check_declared(memberships, profiles)
    _day, _currency, stores, _items, pages = load_locked()
    stores = apply_memberships(stores, declared, profiles)
    if source != "cache":
        _refuse_live(source)
        raise SolverError(f"unsupported solve source {source!r}")
    items, events = offers_from_cache(_cache(app), pages, source="cache")
    items = _drop_excluded_store_offers(stores, items)
    payload = solution_payload(
        stores,
        items,
        require_romanian_store=require_romanian_store,
        excluded_stores=excluded_for_unresolved_fees(),
        plan_ctx=context_from_locked(stores, items, pages, events, locked_shop_rows()),
        selected_store_ids=selected_store_ids,
        edition_pins=edition_pins,
    )
    payload["memberships"] = memberships_payload(stores, declared, profiles)
    payload["source"] = "cache"
    payload["pages"] = events
    return events, payload


# Stores the locked basket is allowed to solve. A given basket that
# includes all of them is the demo re-solve (edition change included).
# eMAG stays off that list while its fee fields are null.
_DEMO_SOLVED_STORE_IDS = frozenset({"libris", "bookzone", "amazon_de"})


def _excluded_for_posted_stores(stores: list) -> list[dict]:
    """Attach the locked exclusion note only for the full demo basket.

    A one-store comparison post must not grow an eMAG note the caller
    did not compare. Null fee fields are copied through unchanged.
    """

    posted = {store.id for store in stores}
    if not _DEMO_SOLVED_STORE_IDS <= posted:
        return []
    return [row for row in excluded_for_unresolved_fees() if row["id"] not in posted]


def _drop_excluded_store_offers(stores: list, items: list[Item]) -> list[Item]:
    """A store left out for an unresolved fee must not re-enter through the cache."""

    allowed = {store.id for store in stores}
    kept: list[Item] = []
    for item in items:
        offers = tuple(offer for offer in item.offers if offer.store_id in allowed)
        if not offers:
            raise SolverError(f"item {item.id!r} has no offers after excluding unresolved fees")
        kept.append(Item(item.id, offers))
    return kept


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


app = create_app()
