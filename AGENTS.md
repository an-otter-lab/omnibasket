# Omnibasket: rules for every agent working in this repo

The plan being built is the Tuesday-to-Wednesday push to the 4 Nov submission; where an older plan disagrees, that plan wins.

## Branches and worktrees
- The main checkout stays on `main` and is used only for merging. Don't work in it directly.
- Each task gets a `feat/<topic>` branch in its own short-lived worktree off `main`, one task per branch.
- A branch merges into `main` once its acceptance checks pass. Remove its worktree in the same step.
- Commit only your own task's files. Never commit a path `.gitignore` lists under "Local only" (`tmp/`, `docs/ops/`, plans, handoffs, evidence screenshots). Those stay on disk in the main checkout; a new kind of internal file gets a line there before its first commit (Adrian, 3 Nov).

## Push and deploy
- `main` is pushed to `origin` only after a merge whose checks are green (`pytest`, `ng test`, `ng build`).
- A feature branch may be pushed to `origin` only to open a PR for review (Grok Bot works this way). Nobody merges a PR on GitHub: merges happen locally into `main` after review.
- The public demo VM deploys `main` from git with `scripts/deploy-vm.sh`.
- The VM gets the search index (`data/index/books.sqlite3`, gitignored) copied by `scripts/deploy-vm.sh`, and `META_API_KEY` from a root-only environment file the systemd unit reads; never from git (Adrian, 31 Oct).
- Until go-live day the public URL shows only a static "Coming soon" page (Adrian, 30 Oct): `omnibasket-gate soon` on the VM. The app is never public before then. Testing uses the Mac's Tailscale URL and SSH tunnels. Only Adrian decides when to switch to `omnibasket-gate live`.
- The repo stays private. Never change its visibility.

## Shops and live reads
- Respect robots.txt and shop terms. Never fetch shop search pages.
- Amazon.de is never read live by the app.
- One honest attempt per page. No bot-wall bypass.
- The user agent names Omnibasket and gives a contact URL. It never contains "spider" or "crawler".
- Tests never touch the network: use fixtures and mocks.
- Book covers come from Open Library only, never from shop images.
- Elefant (T2, 3 Nov, Adrian): index its imported books only (slugs ending in a binding), read its pages with `api/elefant_page.py` (plain code, never Muse), rank an offer only when the page names Elefant as seller, and charge 9,99 lei per order. Cărturești is not added (Cloudflare challenge for everyone).
- Shops (T2, 2026-11-03, Adrian): Elefant replaces Books-Express on the public app; Books-Express (gzip bomb to the VM) is out of the indexed and live shop set (`data/shops/retired/`), and Cărturești stays out. No proxy, new IP or Mac relay for either.
- A shop's data file may declare that the shop sells only its own stock. Its live offers then count as sold by the shop (`direct`) toward its free-delivery threshold, with no per-page model read. Shops with marketplace sellers (eMAG, Amazon.de) stay `unknown` unless the page names the seller (Adrian, 30 Oct).

## Models and money
- Every model call goes through `tools/meta_budget.py`. Commit `data/meta-spend.jsonl` after any model run.
- Never call a model API directly; scripts in `tmp/` included. `config/spend-windows.json` holds the caps that `meta_budget.py` enforces on every call. Spend caps (T2, 3 Nov, Adrian): no lifetime cap; Meta and Baseten are each capped at USD 10 per Bucharest day with no end date, go-live included. Each window (`"period": "day"`, `"gates": "own"`) stops only its own provider; when Baseten's is full, Ask and free text fall back to Muse Spark 1.3. Never edit a window or re-enable a disabled key; only Adrian lifts a cap.
- Prices, ISBN checks, currency conversion and all money arithmetic are plain code, never a model.
- Every number in a model's output is checked against captured data before it is shown.

## Secrets
- No keys, tokens or `.env` files in git.
- Never print a secret in logs, chat or docs.

## Submission claims
- Models (T2, 3 Nov, Adrian; replaces the 2 Nov "1.3 only" rule): Muse Spark Open on Baseten (`meta-models/muse-spark-open-1026`) runs Ask Omnibasket and the free-text parse, with Muse Spark 1.3 as fallback. Everything else stays on Muse Spark 1.3 on the Meta Model API. The lane list is `OPEN_WEIGHT_NOTES` in `tools/meta_budget.py`. Claim an open-weight number only if a `"provider": "baseten"` ledger row backs it.
- The public tree is a client deliverable: no shop screenshots or copied shop text, no internal plans, no exploration scripts, no local paths or IPs. The spend ledger and `docs/ground-truth.xlsx` stay (Adrian, 2 Nov).

## Copy
- Say "order" in EN and "comandă" in RO, never "parcel".
- The entry screen keeps its headline, subtitle, field, Find book, Photo of a list and footnote in every state; with books in the basket only How it works gives way to the basket chips (Adrian, 31 Oct).
- A button that starts a request (Find book, Photo of a list) shows its loading state and is disabled until the answer comes back (Adrian, 31 Oct).
- A book in the basket that is in none of the orders is named next to the orders, with why ("no shop we read has it"), and links to its row; the counts never leave it unexplained (Adrian, 31 Oct).
- Search hides titles with strong profanity (it is a children's books demo) unless the shopper typed such a word or searched by ISBN; hidden, not ranked lower (Adrian, 1 Nov).
- A priced printing in another language than the book the shopper picked carries its language on the book's chip in the order card, e.g. "Matilda · RO" (Adrian, 31 Oct).
- Ask exclusions (T2, 2026-11-03, Adrian): leaving a shop out gives the cheapest plan over the remaining shops, not the default Custom set.
