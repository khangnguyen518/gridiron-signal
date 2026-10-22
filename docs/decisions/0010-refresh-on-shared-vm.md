# 0010. Refresh on the shared loader VM, after sports_db

- Status: Accepted
- Date: 2026-10-22
- Built: code yes (`nflm refresh`, `deploy/`). VM setup pending: needs `deploy/setup_gcp.sh` and `deploy/setup_vm.sh`.

## Context
Tables here went stale whenever nobody ran `dbt build` on a laptop, and the laptop read sports_db's
dev layer, which only refreshes when someone builds dev. sports_db already runs daily on the shared
VM `sports-vm` (sports_db decision 0016) and builds its prod layer, `staging`.

## Decision
- Run on `sports-vm` as Linux user `gridiron`, with its own clone, `.env`, logs and crontab, the same
  pattern as sports_db.
- Read sports_db's prod `staging`; write a prod dataset `nflm` (dbt target `prod`). Laptops keep
  `nflm_dev` and `dev_staging`.
- `nflm refresh` at 10:15 UTC: skip and alert unless sports_db's prod build succeeded within 30 hours,
  then `dbt build --target prod`. Failures post to sports_db's Discord webhook secret.
- `nflm league --refresh --discord` on Sunday 15:30 and Thursday 21:00 UTC.
- The live model card is committed at `model/model_card.json`, so the VM needs no backtest outputs.
  Backtests stay on a laptop.

## Why
- One VM stays in the free tier. The refresh is light (BigQuery does the work).
- The freshness check stops a build on half-loaded inputs. Time order alone would not, the day
  sports_db runs late or fails.
- Reading prod `staging` ties freshness to the VM's schedule, not to whoever last built dev.
- A committed model card makes deploying a model an explicit commit.

## Consequences
- The VM account gets BigQuery job user and `dataEditor` on `nflm`, and `dataViewer` on `ff_marts`
  and `ff_raw` (the draft helper's marts are views over its raw tables),
  in gen-lang-client-0525946386. It already has `roles/editor` in the NBA project (sports_db 0016),
  so keep only trusted code on the VM.
- Four workloads share 1 GB of RAM. The lineup post loads a few hundred MB; it runs when nothing else does.
- Code changes need a manual pull on the VM (deploy/README.md).
