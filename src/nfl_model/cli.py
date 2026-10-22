"""Command line entry point.

uv run nflm backtest [--refresh]
uv run nflm league [--league-id ID] [--user NAME] [--week N]
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

    args = parser.parse_args()
    if args.command == "backtest":
        from nfl_model import backtest

        backtest.main(refresh=args.refresh, skip_tune=args.skip_tune)
    elif args.command == "league":
        from nfl_model import config, data, league

        if args.refresh:
            data.load_player_games(refresh=True)
            data.load_team_games(refresh=True)
            data.load_xwalk(refresh=True)
        league_id = args.league_id or config.SLEEPER_LEAGUE_ID
        if not league_id:
            raise SystemExit("Pass --league-id or set SLEEPER_LEAGUE_ID in .env")
        league.run(league_id, args.user or config.SLEEPER_USERNAME, args.week)


if __name__ == "__main__":
    main()
