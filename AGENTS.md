# Omnibasket: rules for every agent working in this repo

The plan being built is `docs/ops/omnibasket-hackathon-push-2026-10-29.md`. Where an older plan disagrees, that plan wins.

## Branches and worktrees
- `~/Projects/omnibasket` stays on `main` and is used only for merging. Don't work in it directly.
- Each task gets a `feat/<topic>-<task>` branch in its own short-lived worktree under `~/Projects/omnibasket-wt/<branch-with-dashes>`.
- A branch merges into `main` once its acceptance checks pass. Remove its worktree in the same step.
- Commit only your own task's files. Never commit `tmp/`, `ui-ux-design/` or `docs/ops/omnibasket-v1-plan.md`.

## Push and deploy
- Only `main` is pushed to `origin`, and only after a merge whose checks are green (`pytest`, `ng test`, `ng build`).
- The public demo VM deploys `main` from git with `scripts/deploy-vm.sh`.
- The repo stays private. Never change its visibility.

## Shops and live reads
- Respect robots.txt and shop terms. Never fetch shop search pages.
- Amazon.de is never read live by the app.
- One honest attempt per page. No bot-wall bypass.
- The user agent names Omnibasket and gives a contact URL. It never contains "spider" or "crawler".
- Tests never touch the network: use fixtures and mocks.
- Book covers come from Open Library only, never from shop images.

## Models and money
- Every model call goes through `tools/meta_budget.py`. Commit `data/meta-spend.jsonl` after any model run.
- Prices, ISBN checks, currency conversion and all money arithmetic are plain code, never a model.
- Every number in a model's output is checked against captured data before it is shown.

## Secrets
- No keys, tokens or `.env` files in git.
- Never print a secret in logs, chat or docs.

## Copy
- Say "order" in EN and "comandă" in RO, never "parcel".
