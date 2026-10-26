# Omnibasket

**One basket, every shop, lowest total.**

Splits a multi-item shopping basket across independent online stores for the lowest real total —
including shipping, per-order fees and the memberships the buyer already pays for — and answers
whether a membership is worth buying for *this* basket.

Built for the [Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
(indie developer track, theme: Build for Your World). Submission due 4 Nov 2026, 9:00 PM ET.

## The problem

A seven-item basket across three stores means three free-shipping thresholds, a per-order fee and
two possible memberships. The cheapest answer is not "buy each item where it is cheapest":

- Paying *more* for one item can cross a store's free-shipping threshold and win the basket.
- A per-order fee makes a tiny extra order a net loss.
- A membership changes the threshold, which changes the optimal split — and may or may not pay for
  itself on this basket.

Books are the launch wedge: a real basket, real ISBNs, and stores that publish their shipping rules.
Nothing in the design is book-specific — the same solve applies to any basket of goods with
per-store thresholds.

## How it works

1. **Read** — Muse Spark (Meta Model API) reads each store's rendered product page and returns a
   fixed schema: price, stock, edition, shipping fee, free-shipping threshold, membership badges.
   No per-store scraper adapters.
2. **Match** — offers are matched on a canonical product identifier (ISBN for books), and wrong
   editions are rejected rather than averaged in.
3. **Solve** — a deterministic optimiser (OR-Tools) assigns each item to a store, with a boolean per
   store for "this store's free-shipping threshold is reached", including per-order fees. Every
   money decision is exact and explainable; the model never does arithmetic.
4. **Decide** — the basket is solved with and without each membership to produce the verdict:
   *is this membership worth it for these seven items?*

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, server-sent events for live read progress |
| Page reading | Playwright, headless Chromium, loaded by product identifier |
| Extraction | Muse Spark via Meta Model API; open-weights fallback (Modal / Baseten); Pydantic schema validation |
| Solver | OR-Tools |
| Storage | SQLite — page cache + ground-truth table |
| Front end | Angular + TypeScript, responsive |

Store data, the detailed plan and the prior-work survey are kept outside this repository until the
submission is in; they are not part of the product.

## Status

Pre-build. Concept, data model and prior-work survey are done; extraction spike, solver and UI are
being built in the hackathon window (27 Oct – 4 Nov 2026).

## Novelty

No consumer tool found combines all three of: independent retailers, per-store free-shipping
thresholds, and the buyer's own memberships. The closest neighbours are single-marketplace cart
optimisers (Cardmarket, TCGplayer, Brick Owl), US-only extensions with no fee modelling (CartHappy),
single-store basket comparison (BasketWise, Australia), and single-item comparison (Meta Muse
shopping, Google Universal Cart). The closest comparison in the same space is single-store basket
comparison; none of them optimise the split under thresholds and memberships.

## Data note

The accuracy test runs against hand-verified store data and cached page snapshots. Those are data
collected for testing, not application code, and they are kept out of this repository; every line of
application code here was written during the hackathon window.

## Risks

- **Stores block agents.** Amazon blocked Meta Muse in September 2026 and its robots.txt names AI
  agents. Mitigation: the recorded demo runs against cached fixtures, with live reads where they
  succeed.
- **Membership badges hidden when logged out.** Mitigation: user-declared memberships plus each
  store's published rules.
- **Location-dependent shipping.** Mitigation: delivery address is a required input.

## Licence

MIT — see `LICENSE`.
