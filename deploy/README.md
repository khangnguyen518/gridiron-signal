# VM runbook

gridiron-signal runs on the shared loader VM `sports-vm` (project nba-analytics-499420, zone
us-west1-c), next to sports_db, the NBA loader and arb-bot. It runs as Linux user `gridiron` from
`/home/gridiron/gridiron-signal`. See decision 0010 and sports_db's decision 0016.

## What runs (UTC)

| Time | Job | Command |
|---|---|---|
| :05 every hour | record Kalshi NFL lines to `nflm_raw` | `nflm record-lines` |
| 08:00 daily | NBA loader | (other project) |
| 09:20 daily | sports_db daily pipeline, about 18 minutes | (sports_db) |
| **10:15 daily** | rebuild this repo's tables in `nflm` | `nflm refresh` |
| **Sun 15:30** | lineup, close calls, waivers to Discord | `nflm league --refresh --discord` |
| **Thu 21:00** | same, before Thursday night | `nflm league --refresh --discord` |

`nflm refresh` first checks sports_db's `raw_meta.load_runs` for a successful prod dbt build in the
last 30 hours. If there is none, it skips and posts to Discord instead of building on stale data.
Any dbt failure also posts. Backtests stay on a laptop: tuning needs more memory than the shared
1 GB VM should give it.

## Before you start
- sports_db must already run on the VM (its `deploy/README.md`).
- Sign in with gcloud as an owner of gen-lang-client-0525946386: `gcloud auth login`.
- The VM runs `main`. Commit `model/model_card.json` when you want a new model live.

## 1. Grants (laptop)
```bash
bash deploy/setup_gcp.sh
```
Safe to rerun. In gen-lang-client-0525946386 the VM's account gets BigQuery job user, `dataEditor`
on the prod dataset `nflm` (created here), `dataViewer` on `ff_marts`, and the custom role
`rawAppender` (append, never delete) on `nflm_raw`. Nothing changes in
sports-db-209650: the account can already read `staging`, `raw_nfl`, `raw_meta` and the alert secret.

## 2. Install on the VM
```bash
gcloud compute scp deploy/setup_vm.sh sports-vm:~ --zone us-west1-c --project nba-analytics-499420 --tunnel-through-iap
gcloud compute ssh sports-vm --zone us-west1-c --project nba-analytics-499420 --tunnel-through-iap -- sudo bash setup_vm.sh
```
It adds the `gridiron` user, uv, a deploy key, the repo, `.env`, log rotation and the crontab. It
pauses and prints a public key. Add it as a read-only deploy key from a laptop, then press Enter:
```bash
gh repo deploy-key add vm_key.pub -R khangnguyen518/gridiron-signal --title sports-vm
```
(Save the printed key to `vm_key.pub` first.)

## 3. League settings (VM)
For the Discord lineup posts, set your league in the VM's `.env`:
```bash
sudo -u gridiron -H bash -lc 'nano ~/gridiron-signal/.env'   # SLEEPER_LEAGUE_ID, SLEEPER_USERNAME
```
The Discord webhook is sports_db's secret `alert-discord-webhook`. Until it has a value, alerts and
posts only go to the logs.

## 4. First run (VM)
```bash
sudo -u gridiron -H bash -lc 'cd ~/gridiron-signal && uv run nflm refresh && uv run nflm league --refresh'
```
Expect every dbt test to pass, plus the documented `lines_before_kickoff` warning.

## Updating code
The VM does not pull on its own. After pushing to `main`:
```bash
gcloud compute ssh sports-vm --zone us-west1-c --project nba-analytics-499420 --tunnel-through-iap -- \
  "sudo -u gridiron -H bash -lc 'cd ~/gridiron-signal && git pull --ff-only && uv sync --locked && crontab deploy/crontab'"
```

## Logs
`/home/gridiron/gridiron-signal/logs/refresh.log`, `record.log` and `league.log`, rotated weekly, 8 kept.

## Line recorder
`nflm record-lines` takes about 8 seconds and peaks near 160 MB (measured 2026-10-22). A failed snapshot posts to Discord;
the next hour's run tries again. Missed hours cannot be filled in later.

## Memory
The refresh is dbt only; BigQuery does the work. `nflm league --refresh` loads about 90k player
games into pandas, a few hundred MB, at times when no other job runs. If the kernel kills it
(`dmesg`), move the lineup post to a laptop or the VM to e2-small.

## Cost
No new VM. BigQuery: the daily build processes about 400 MB, inside the free tier. The line
recorder appends about 700 market rows an hour at about 140 bytes each, roughly 0.4 GB a season,
inside the 10 GB of free storage. Load jobs are free.
