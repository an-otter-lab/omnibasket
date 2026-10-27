"""FastAPI routes for health, cache-only solve, and page-read events."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.basket import load_locked
from api.cache import PageCache, open_seeded
from api.solve_service import items_from_body, solution_payload, stores_from_body
from solver.optimize import SolverError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "cache" / "ro-v1.sqlite"
UI_DIST = ROOT / "ui" / "dist" / "ui" / "browser"


class OfferIn(BaseModel):
    store_id: str
    price_cents: int
    seller_certainty: str


class ItemIn(BaseModel):
    id: str
    offers: list[OfferIn]


class StoreIn(BaseModel):
    id: str
    currency: str
    free_shipping_threshold_cents: int
    shipping_fee_cents: int
    per_order_fee_cents: int


class SolveIn(BaseModel):
    stores: list[StoreIn] | None = None
    items: list[ItemIn] | None = None
    source: str = Field(default="cache")


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Omnibasket", version="v1")
    path = db_path or DEFAULT_DB
    app.state.db_path = path

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/solve")
    def solve_route(body: SolveIn | None = None, source: str = Query(default="cache")) -> JSONResponse:
        mode = body.source if body and body.source else source
        try:
            payload = _solve(app, body, mode)
        except SolverError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        return JSONResponse(payload)

    @app.get("/events")
    def events(source: str = Query(default="cache")) -> StreamingResponse:
        def generate():
            try:
                pages, payload = _cached_solution(app, source)
            except SolverError as exc:
                yield _sse("error", {"error": str(exc)})
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


def _solve(app: FastAPI, body: SolveIn | None, source: str) -> dict:
    if body and body.stores and body.items:
        if source not in {"given", "cache"}:
            raise SolverError(f"unsupported solve source {source!r}")
        # A caller-supplied basket is arithmetic only. It does not fetch pages.
        stores = stores_from_body([row.model_dump() for row in body.stores])
        items = items_from_body([row.model_dump() for row in body.items])
        return solution_payload(stores, items)
    _, payload = _cached_solution(app, source)
    return payload


def _cached_solution(app: FastAPI, source: str) -> tuple[list[dict], dict]:
    from api.solve_service import offers_from_cache

    _day, _currency, stores, _items, pages = load_locked()
    if source != "cache":
        raise SolverError("live solve is not the demo path; use source=cache")
    items, events = offers_from_cache(_cache(app), pages, source="cache")
    payload = solution_payload(stores, items)
    payload["source"] = "cache"
    payload["pages"] = events
    return events, payload


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
