"""Command line entry point.

uv run nflm backtest [--refresh]
uv run nflm league [--league-id ID] [--user NAME] [--week N] [--refresh] [--discord]
uv run nflm refresh [--force]
uv run nflm record-lines
uv run nflm log-projections [--week N]
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="nflm")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="tune, walk-forward backtest, compare with Sleeper")
    bt.add_argument("--refresh", action="store_true", help="re-read BigQuery instead of the cache")
    bt.add_argument("--skip-tune", action="store_true", help="reuse the last run's tuned half-lives")

    lg = sub.add_parser("league", help="lineup, close calls and waiver targets for a Sleeper league")
    lg.add_argument("--league-id", help="Sleeper league ID (default SLEEPER_LEAGUE_ID in .env)")
    lg.add_argument("--user", help="your Sleeper display name (default SLEEPER_USERNAME in .env)")
    lg.add_argument("--week", type=int, help="NFL week (default: Sleeper's current week)")
    lg.add_argument("--refresh", action="store_true", help="re-read BigQuery instead of the cache")
    lg.add_argument("--discord", action="store_true", help="also post a summary to the alert webhook")

    rf = sub.add_parser("refresh", help="check sports_db freshness, then dbt build (for cron)")
    rf.add_argument("--force", action="store_true", help="build even if sports_db did not build recently")

    sb = sub.add_parser("sim-backtest", help="calibrate and test the game simulation's ranges")
    sb.add_argument("--refresh", action="store_true", help="re-read BigQuery instead of the cache")
    sub.add_parser("record-lines", help="append a snapshot of Kalshi NFL markets and lines (for cron)")
    lp = sub.add_parser("log-projections", help="append this week's live projections to BigQuery (for cron)")
    lp.add_argument("--week", type=int, help="NFL week (default: Sleeper's current week)")

    args = parser.parse_args()
    if args.command == "backtest":
        from nfl_model import backtest

        backtest.main(refresh=args.refresh, skip_tune=args.skip_tune)
    elif args.command == "league":
        from nfl_model import config, data, league

        if args.refresh:
            data.refresh_all()  # status and depth too: they carry this week's practice status and depth charts
        league_id = args.league_id or config.SLEEPER_LEAGUE_ID
        if not league_id:
            raise SystemExit("Pass --league-id or set SLEEPER_LEAGUE_ID in .env")
        league.run(league_id, args.user or config.SLEEPER_USERNAME, args.week, discord=args.discord)
    elif args.command == "refresh":
        import sys

        from nfl_model import refresh

        sys.exit(refresh.main(force=args.force))
    elif args.command == "sim-backtest":
        from nfl_model import sim_backtest

        sim_backtest.main(refresh=args.refresh)
    elif args.command == "record-lines":
        import sys

        from nfl_model import record

        sys.exit(record.main())
    elif args.command == "log-projections":
        import sys

        from nfl_model import projlog

        sys.exit(projlog.main(week=args.week))


if __name__ == "__main__":
    main()
