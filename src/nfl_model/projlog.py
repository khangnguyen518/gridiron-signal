"""Log live projections for a forward test (decision 0019).

    uv run nflm log-projections [--week N]

Builds the league tool's full player table for this week (the league's own scoring, every
adjustment, simulated ranges) and appends it to NFLM_RAW_DATASET.projection_snapshots, one row
per player per snapshot. Run on the VM daily at 15:00 UTC and Sunday at 16:45 UTC (after
inactives for 1 p.m. ET games). The evaluation is fixed in decision 0019: for each player-game,
the last prod snapshot before kickoff, against league-scored actuals and Sleeper's live projection.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime

import pandas as pd
import requests
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery

from nfl_model import alerts, config, data, league, sleeper
from nfl_model.live import AllGamesPlayed
from nfl_model.record import _append

S = bigquery.SchemaField
SCHEMA = [
    S("snapshot_at", "TIMESTAMP", "REQUIRED"),
    S("season", "INTEGER", "REQUIRED"),
    S("week", "INTEGER", "REQUIRED"),
    S("league_id", "STRING"),
    S("dbt_target", "STRING"),
    S("model_card_sha", "STRING"),
    S("git_commit", "STRING"),
    S("scoring_sha", "STRING"),
    S("sleeper_id", "STRING", "REQUIRED"),
    S("gsis_id", "STRING"),
    S("name", "STRING"),
    S("position", "STRING"),
    S("team", "STRING"),
    S("opponent", "STRING"),
    S("kickoff_utc", "TIMESTAMP"),
    S("role_label", "STRING"),
    S("injury_status", "STRING"),
    S("practice_status", "STRING"),
    S("flag", "STRING"),
    S("proj", "FLOAT"),  # shown projection: the shifted blend, x Questionable factors
    S("center", "FLOAT"),  # expected points: lineup ranking and the expected total
    S("p10", "FLOAT"),
    S("p50", "FLOAT"),
    S("p90", "FLOAT"),
    S("ours", "FLOAT"),
    S("sleeper", "FLOAT"),  # Sleeper's live projection at snapshot time
    S("blend_w", "FLOAT"),
    S("blend_shift", "FLOAT"),
    S("blend_matchup", "FLOAT"),
    S("q_play", "FLOAT"),
    S("q_mult", "FLOAT"),
    S("implied_points", "FLOAT"),
    S("spread", "FLOAT"),
    S("line_source", "STRING"),
]
STRINGS = [f.name for f in SCHEMA if f.field_type == "STRING"]
FLOATS = [f.name for f in SCHEMA if f.field_type == "FLOAT"]


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            cwd=config.ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def snapshot_rows(players: pd.DataFrame, at: datetime, season: int, week: int, meta: dict) -> pd.DataFrame:
    """The league tool's player table as log rows, in SCHEMA order and types."""
    df = players.copy()
    df["team"] = df["sleeper_team"].fillna(df["team"]) if "sleeper_team" in df else df["team"]
    for col in [f.name for f in SCHEMA]:
        if col not in df:
            df[col] = None
    df["snapshot_at"], df["season"], df["week"] = at, season, week
    for key, value in meta.items():
        df[key] = value
    df["kickoff_utc"] = pd.to_datetime(df["kickoff_utc"], utc=True)
    df[FLOATS] = df[FLOATS].apply(pd.to_numeric, errors="coerce")
    df[STRINGS] = df[STRINGS].astype("string")
    return df[[f.name for f in SCHEMA]].dropna(subset=["sleeper_id"]).reset_index(drop=True)


def main(week: int | None = None) -> int:
    at = datetime.now(UTC)
    league_id = config.SLEEPER_LEAGUE_ID
    if not league_id:
        print("Set SLEEPER_LEAGUE_ID in .env: projections are scored with the league's settings.")
        return 1
    try:
        data.refresh_all()
        lg, st = sleeper.league(league_id), sleeper.state()
        season = int(lg.get("season") or st["season"])
        week = week or int(st["week"])
        scoring = {k: float(v) for k, v in (lg.get("scoring_settings") or {}).items()}
        players, notes, _ = league.build_player_table(season, week, scoring)
        meta = {
            "league_id": league_id,
            "dbt_target": config.NFLM_DBT_TARGET,
            "model_card_sha": _sha(config.MODEL_CARD.read_bytes()) if config.MODEL_CARD.exists() else None,
            "git_commit": _git_commit(),
            "scoring_sha": _sha(json.dumps(scoring, sort_keys=True).encode()),
        }
        # Kickoff for every row (kickers, defenses and players without our projection too), from
        # each team's game this week: the evaluation takes the last snapshot before kickoff
        tg = data.load_team_games()
        games = tg[(tg["season"] == season) & (tg["week"] == week)].set_index("team")["kickoff_utc"]
        players["kickoff_utc"] = (
            players["kickoff_utc"].fillna(players["team"].map(games))
            if "kickoff_utc" in players
            else players["team"].map(games)
        )
        rows = snapshot_rows(players, at, season, week, meta)
        client = bigquery.Client(project=config.NFLM_GCP_PROJECT)
        n = _append(client, "projection_snapshots", rows, SCHEMA, clustering=["week", "position"])
    except AllGamesPlayed as exc:  # Tuesday before Sleeper moves to the next week: nothing to log
        print(f"{at:%Y-%m-%d %H:%M} UTC: nothing to log ({exc})")
        return 0
    except (requests.RequestException, GoogleAPIError, KeyError, ValueError) as exc:
        alerts.send(f"gridiron-signal log-projections failed at {at:%Y-%m-%d %H:%M} UTC: {exc!r}")
        return 1
    for note in notes:
        print(f"Note: {note}")
    print(f"{at:%Y-%m-%d %H:%M} UTC: logged {n} player projections for {season} week {week}")
    return 0
