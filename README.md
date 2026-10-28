# Omnibasket

**One basket, every shop, lowest total.**

Splits a multi-item shopping basket across independent online stores for the lowest real total,
including shipping and per-order fees. The pitch is a Romanian parent splitting a children's book
order across local shops. The United States is parked: only Amazon.com loaded cleanly from this
machine, and a Romanian egress distorts US prices.

Built for the [Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
(indie developer track, theme: Build for Your World). Submission due 4 Nov 2026, 9:00 PM ET.

## The problem

A seven-item basket across several stores means several free-shipping thresholds and a per-order fee.
The cheapest answer is not "buy each item where it is cheapest":

- Paying *more* for one item can cross a store's free-shipping threshold and win the basket.
- A per-order fee makes a tiny extra order a net loss.

Books are the launch wedge: a real basket, real ISBNs, and stores that publish their shipping rules.
Nothing in the design is book-specific — the same solve applies to any basket of goods with
per-store thresholds.

## How it works

1. **Read** — Muse Spark (Meta Model API) reads each store's rendered product page and returns a
   fixed schema: price, stock, edition, shipping fee, free-shipping threshold, membership badges.
   No per-store scraper adapters.
2. **Match** — offers are matched on a canonical product identifier (ISBN for books), and wrong
   editions are rejected rather than averaged in.
3. **Solve** — `solver/` assigns each item to a store by exhaustive search over integer cents, including
   per-order fees and whether a store's free-shipping threshold is reached. Every money decision is
   exact. The model never does arithmetic.
4. **Show** — the cache-first service returns that split, and the Angular screen shows it. A second
   solve with the shopper's own prices is how the edition toggle (same story, or exact ISBN) is applied.

## Stack

| Layer | What is built |
|---|---|
| Backend | Python, FastAPI. `POST /solve` and `GET /events` (server-sent events). The built UI is served from the same app. |
| Page reading | Cache-first. Saved pages live in a SQLite page cache. The reading spike (Playwright plus a fixed schema) is separate from the demo path. |
| Read layer | `matching/` normalises ISBNs, keeps seller certainty tri-state, and matches editions instead of averaging them. |
| Solver | `solver/`: exhaustive assignment in integer cents. Fifteen tests in `solver/tests/`. |
| Storage | SQLite page cache, seeded from the locked Romanian basket. |
| Front end | Angular and TypeScript in `ui/`, responsive. The membership control stays disabled: the service returns an empty membership list. |
| Stores | Bookzone, eMAG, Libris and Amazon.de for the locked basket. Books-Express is a labelled fallback, not a core store. |

## Run the demo

One command from a fresh clone. It creates a Python 3.12 virtualenv, installs the pinned
dependencies in `requirements.txt`, builds the Angular UI, seeds the SQLite page cache from
`data/cache/ro-v1-seed.json`, and serves the API and the built UI together.

You need [uv](https://docs.astral.sh/uv/) and Node.js (npm). No API key is required: the demo
reads the seeded cache and does not call a store or a model.

```bash
./scripts/start-demo.sh
```

Then open http://127.0.0.1:8000 . `GET /health` returns `{"status":"ok"}`.

## Status

The v1 tree is a working cache-first demo.

- A locked seven-book Romanian basket (`ro-v1`): Ghici, The Very Hungry Caterpillar, Owl Babies, and four Amazon.de titles that share an ISBN with Libris.
- An exhaustive integer-cents solver in `solver/`, with 15 passing tests.
- A read layer in `matching/` with the three spike fixes: ISBN check digits, sold-by tri-state, and edition matching that does not average different books.
- A cache-first service (`api/`) and the Angular UI (`ui/`), which the API serves after `ng build`. The demo runs on cached pages and says so.

Membership is not implemented. The service returns an empty membership list and the UI control is disabled. No Genius-badged eMAG-sold title was found for this basket.

## Novelty

No consumer tool found combines independent retailers with per-store free-shipping thresholds on one basket. The closest neighbours are single-marketplace cart
optimisers (Cardmarket, TCGplayer, Brick Owl), US-only extensions with no fee modelling (CartHappy),
single-store basket comparison (BasketWise, Australia), and single-item comparison (Meta Muse
shopping, Google Universal Cart). Full survey with sources: `docs/prior-work.xlsx`.

## Data note

`docs/ground-truth.xlsx` is hand-verified store data used as the extraction accuracy test and as
cached page fixtures for the recorded demo. It is **data collected for testing**, not application
code; all application code here was written during the hackathon window.

## Risks

- **Stores block agents.** Amazon blocked Meta Muse in September 2026 and its robots.txt names AI
  agents. Mitigation: the recorded demo runs against cached fixtures, with live reads where they
  succeed.
- **Membership badges hidden when logged out.** Mitigation: user-declared memberships plus each
  store's published rules.
- **Location-dependent shipping.** Mitigation: delivery address is a required input.

## Licence

MIT — see `LICENSE`.
