# Omnibasket: rules for every agent working in this repo

The plan being built is `docs/ops/omnibasket-hackathon-push-2026-10-29.md`. Where an older plan disagrees, that plan wins.

## Branches and worktrees
- `~/Projects/omnibasket` stays on `main` and is used only for merging. Don't work in it directly.
- Each task gets a `feat/<topic>-<task>` branch in its own short-lived worktree under `~/Projects/omnibasket-wt/<branch-with-dashes>`.
- A branch merges into `main` once its acceptance checks pass. Remove its worktree in the same step.
- Commit only your own task's files. Never commit `tmp/`, `ui-ux-design/` or `docs/ops/omnibasket-v1-plan.md`.

## Push and deploy
- `main` is pushed to `origin` only after a merge whose checks are green (`pytest`, `ng test`, `ng build`).
- A feature branch may be pushed to `origin` only to open a PR for review (Grok Bot works this way). Nobody merges a PR on GitHub: merges happen locally into `main` after review.
- The public demo VM deploys `main` from git with `scripts/deploy-vm.sh`.
- Until go-live day the public URL shows only a static "Coming soon" page (Adrian, 30 Oct): `omnibasket-gate soon` on the VM. The app is never public before then. Testing uses the Mac's Tailscale URL and SSH tunnels. Only Adrian decides when to switch to `omnibasket-gate live`.
- The repo stays private. Never change its visibility.

## Shops and live reads
- Respect robots.txt and shop terms. Never fetch shop search pages.
- Amazon.de is never read live by the app.
- One honest attempt per page. No bot-wall bypass.
- The user agent names Omnibasket and gives a contact URL. It never contains "spider" or "crawler".
- Tests never touch the network: use fixtures and mocks.
- Book covers come from Open Library only, never from shop images.
- A shop's data file may declare that the shop sells only its own stock. Its live offers then count as sold by the shop (`direct`) toward its free-delivery threshold, with no per-page model read. Shops with marketplace sellers (eMAG, Amazon.de) stay `unknown` unless the page names the seller (Adrian, 30 Oct).

## Models and money
- Every model call goes through `tools/meta_budget.py`. Commit `data/meta-spend.jsonl` after any model run.
- Never call a model API directly; scripts in `tmp/` included. `config/spend-windows.json` holds dated caps that `meta_budget.py` enforces on every call: until submission (Wed 4 Nov), at most USD 10 of Meta credits per day, weekends included (Adrian, 30 Oct). Never edit a window or re-enable a disabled key; only Adrian lifts a cap.
- Prices, ISBN checks, currency conversion and all money arithmetic are plain code, never a model.
- Every number in a model's output is checked against captured data before it is shown.

## Secrets
- No keys, tokens or `.env` files in git.
- Never print a secret in logs, chat or docs.

## Copy
- Say "order" in EN and "comandă" in RO, never "parcel".
- The entry screen keeps its headline, subtitle, field, Find book, Photo of a list and footnote in every state; with books in the basket only How it works gives way to the basket chips (Adrian, 31 Oct).
