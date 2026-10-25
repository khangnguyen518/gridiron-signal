# VM runbook

gridiron-signal runs on the shared loader VM `sports-vm` (project nba-analytics-499420, zone
us-west1-c), next to sports_db, the NBA loader and arb-bot. It runs as Linux user `gridiron` from
`/home/gridiron/gridiron-signal`. See decision 0010 and sports_db's decision 0016.

## What runs (UTC)

| Time | Job | Command |
|---|---|---|
| :05 every hour | record Kalshi NFL lines and player props to `nflm_raw` | `nflm record-lines` |
| 08:00 daily | NBA loader | (other project) |
| 09:20 daily | sports_db daily pipeline, about 18 minutes | (sports_db) |
| **10:15 daily** | rebuild this repo's tables in `nflm` | `nflm refresh` |
| **15:00 daily** | log this week's live projections (forward test, decision 0019) | `nflm log-projections` |
| **Sun 15:30** | lineup, close calls, waivers to Discord | `nflm league --refresh --discord` |
| **Sun 16:45** | log projections again, after inactives for 1 p.m. ET games | `nflm log-projections` |
| **Thu 21:00** | same, before Thursday night | `nflm league --refresh --discord` |

The league and projection-log jobs share a lock and wait for each other (`flock -w 1200`), so on the
1 GB VM they never run at once and neither is skipped.

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
on the prod dataset `nflm` (created here), `dataViewer` on `ff_marts` and `ff_raw` (the marts are views over raw), and the custom role
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
`/home/gridiron/gridiron-signal/logs/refresh.log`, `record.log`, `league.log` and `projlog.log`, rotated weekly, 8 kept.

## Line recorder
`nflm record-lines` takes about 8 seconds and peaks near 160 MB (measured 2026-10-22); the player-prop pull
adds about 3 seconds and runs after the game lines (0015). A failed snapshot posts to Discord, game lines and props
separately; the next hour's run tries again. Missed hours cannot be filled in later.

## Memory
The refresh is dbt only; BigQuery does the work. `nflm league --refresh` loads about 90k player
games into pandas and simulates 1,000 games per player: about 540 MB on the VM before the
simulation, about 145 MB more with it (measured on a laptop), at times when no other job runs. If the kernel kills it
(`dmesg`), move the lineup post to a laptop or the VM to e2-small.

## Cost
No new VM. BigQuery: the daily build processes about 400 MB, inside the free tier. The line
recorder appends about 700 market rows an hour at about 140 bytes each, roughly 0.4 GB a season,
plus about 4,400 player-prop rows an hour at about 300 bytes, roughly 4 GB a season (0015). Together
they fit the 10 GB of free storage this season; beyond it storage is about $0.02 a GB a month. Load jobs are free.
