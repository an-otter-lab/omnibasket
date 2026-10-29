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

1. **Read** — Muse Spark turns each saved product page into a structured offer: title, ISBN, price,
   currency, edition, stock, and the delivery or fee lines the page prints. The demo replays the saved
   reads; nothing is fetched live.
2. **Match** — offers are matched by ISBN, with edition rules applied per book, and the app checks each
   Muse Spark read against the page it was read from. A read that disagrees is shown on the offer as a
   mismatch and never replaces the captured price. The edition pin lets you keep the same-story default
   or require the exact edition.
3. **Solve** — `POST /solve` computes assignments and delivery costs in integer cents. Unknown fees are not printed and are never treated as zero.
4. **Compare** — the UI presents three result tabs: **1 parcel**, **cheapest**, and **custom stores**. Cheapest assigns each book for the lowest valid basket total. In custom stores, every switched-on shop must take at least one book; books move among enabled shops in the cheapest way. If an enabled shop cannot be served, no custom total is shown.
5. **Inspect** — book details include links to the real shop offers, so you can open the underlying listing, and each offer says whether Muse Spark read it and whether the read matches the page.

## Front end

The responsive Angular UI shows the three solve results as tabs: **1 parcel** (one shop for the whole basket), **cheapest** (lowest basket total), and **custom stores** (choose the shops allowed to participate). Custom-store assignments ensure each selected shop receives at least one book, then place books as cheaply as possible; if any selected shop has no usable offer, the UI withholds a total rather than implying it can fulfill the selection. Each book detail exposes real shop links. The edition pin controls whether matching accepts the same story or requires the exact ISBN; changing it reruns `/solve`. Search-by-title is not available in the app.

## Stack

| Layer | What is built |
|---|---|
| Backend | Python, FastAPI. `POST /solve` and `GET /events` (server-sent events). The built UI is served from the same app. |
| Page reading | Cache-first. Saved pages live in a SQLite page cache, each with its Muse Spark read. The capture spike (Playwright) and the reader (`tools/muse_reads.py`) are separate from the demo path. |
| Read layer | `matching/` normalises ISBNs, keeps seller certainty tri-state, and matches editions instead of averaging them. |
| Solver | `solver/`: exhaustive assignment in integer cents. Tests in `solver/tests/`, including the Romanian basket. |
| Storage | SQLite page cache, seeded from the locked Romanian basket. |
| Front end | Angular and TypeScript in `ui/`, responsive. The membership control stays disabled: the service returns an empty membership list. |
| Stores | Bookzone, eMAG, Libris and Amazon.de for the locked basket. Books-Express is a labelled fallback, not a core store. |

## Run the demo

One command from a fresh clone. It creates a Python 3.12 virtualenv, installs the pinned
dependencies in `requirements.txt`, builds the Angular UI, seeds the SQLite page cache from
`data/cache/ro-v1-seed.json`, and serves the API and the built UI together.

You need [uv](https://docs.astral.sh/uv/) and Node.js (npm). No API key is required: the demo replays
the saved reads and calls neither a store nor a model. The reads are re-run with a key, one Muse Spark
call per saved page, in replay mode:

```bash
META_API_KEY=<key> python3 tools/muse_reads.py
```

Every call is written to the spend ledger by `tools/meta_budget.py`, with a job stop short of USD 1.

```bash
./scripts/start-demo.sh
```

Then open http://127.0.0.1:8000 . `GET /health` returns `{"status":"ok"}`.

## Status

The v1 tree is a working cache-first demo.

- A locked seven-book Romanian basket (`ro-v1`): Ghici, The Very Hungry Caterpillar, Owl Babies, and four Amazon.de titles that share an ISBN with Libris.
- An exhaustive integer-cents solver in `solver/`. The UI compares one-parcel (**558.73 lei** via Libris), cheapest (**515.16 lei**), and custom stores (**530.45 lei** for Amazon.de + Libris + Bookzone, with Ghici assigned to Bookzone).
- Bookzone under 200 lei is delivery from **10.90 lei** plus **1.99 lei** processing (cart at bookzone.ro/cos/produse), not the earlier lower delivery line.
- Amazon.de free delivery to Romania starts at **262.17 lei** (printed on the Amazon.de product pages, read 28 Oct 2026; the lei value moves with the exchange rate). The under-threshold per-delivery and per-kg amounts are unknown and are not priced. eMAG is excluded because its three solver fee fields are null.
- A read layer in `matching/` with the three spike fixes: ISBN check digits, sold-by tri-state, and edition matching that does not average different books.
- Every one of the 15 saved pages carries a Muse Spark 1.3 read, stored with the page and checked
  against the captured price: 15 match, 0 mismatch, USD 0.19 for the job. Book detail says which
  offers were read, and shows a solid orange tag when a read disagrees with the page.
- A cache-first service (`api/`) and the Angular UI (`ui/`), which the API serves after `ng build`. The demo runs on cached pages, shows the three result tabs, and says the pages are cached.

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
