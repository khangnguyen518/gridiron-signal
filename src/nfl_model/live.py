"""Projections for an upcoming week.

Each player with an earlier NFL game gets a placeholder row for this week's game
(no stats, played = 0). The same feature code as the backtest then sees only
earlier games, so live and backtest projections are built the same way.
Lines come from Kalshi when listed, else the latest nflverse line.
"""

import json

import numpy as np
import pandas as pd
import requests

from nfl_model import config, data, lines, matchup, questionable, sleeper
from nfl_model.availability import Renorm, add_roster_rows, add_team_usual, renormalize
from nfl_model.backtest import VARIANTS, latest_run_dir, prepare
from nfl_model.features import Params, add_player_features, add_team_features, season_priors
from nfl_model.model import fit_volume_models, predict_volume, project
from nfl_model.roles import RoleParams, apply_roles

# Stat columns a placeholder row carries as zero: nothing is known about this game yet
# Seasons of history kept for live features. Usage has a 2-game half-life, so older games barely
# count; position priors still use every season. Keeps memory down on the shared VM.
LIVE_HISTORY_SEASONS = 3
# Sleeper injury statuses that mean "not playing" for renormalization (midweek variant)
INACTIVE_STATUSES = {"Out", "IR", "PUP", "Sus", "NA", "DNR", "Doubtful"}

ZERO_COLS = [
    "pass_attempts",
    "completions",
    "pass_yards",
    "pass_tds",
    "interceptions",
    "pass_2pt",
    "carries",
    "rush_yards",
    "rush_tds",
    "rush_2pt",
    "targets",
    "receptions",
    "rec_yards",
    "rec_tds",
    "rec_2pt",
    "air_yards",
    "fumbles_lost",
    "rz_targets",
    "rz_carries",
    "fantasy_points",
    "team_points",
    "team_pass_attempts",
    "team_rush_attempts",
    "team_rz_pass_attempts",
    "team_rz_rush_attempts",
]


def load_model_card() -> dict:
    """The committed model card, else the newest backtest run's."""
    if config.MODEL_CARD.exists():
        return json.loads(config.MODEL_CARD.read_text())
    run = latest_run_dir()
    if run is None:
        raise SystemExit("No model card. Run `uv run nflm backtest` first.")
    return json.loads((run / "model_card.json").read_text())


def week_lines(tg: pd.DataFrame, season: int, week: int) -> tuple[pd.DataFrame, str]:
    """This week's team rows, with Kalshi lines in place of nflverse where Kalshi lists the game."""
    wk = tg[(tg["season"] == season) & (tg["week"] == week)].copy()
    home = wk[wk["is_home"]]
    games = pd.DataFrame(
        {"game_id": home["game_id"], "home_team": home["team"], "away_team": home["opponent"]}
    )
    try:
        kalshi = lines.lines_for_games(games)
    except (requests.RequestException, KeyError, ValueError) as exc:  # Kalshi down must not block projections
        print(f"Kalshi lines unavailable ({exc}); using nflverse lines")
        kalshi = pd.DataFrame(columns=["game_id", "spread_line", "total_line"])
    kalshi = kalshi.rename(columns={"spread_line": "k_home_spread", "total_line": "k_total"})
    wk = wk.merge(kalshi, on="game_id", how="left")

    use_k = wk["k_home_spread"].notna() & wk["k_total"].notna()
    side = np.where(wk["is_home"], 1.0, -1.0)
    wk["line_source"] = np.where(use_k, "kalshi", np.where(wk["spread"].notna(), "nflverse", "none"))
    wk["spread"] = np.where(use_k, side * wk["k_home_spread"], wk["spread"])
    wk["total_line"] = np.where(use_k, wk["k_total"], wk["total_line"])
    wk["implied_points"] = (wk["total_line"] + wk["spread"]) / 2
    wk = wk.drop(columns=["k_home_spread", "k_total"])

    sources = wk.drop_duplicates("game_id")["line_source"].value_counts().to_dict()
    return wk, ", ".join(f"{n} games from {src}" for src, n in sources.items())


def project_week(
    season: int, week: int, scoring: dict[str, float] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """One row per skill player with NFL history on a team playing this week.
    Returns (projections keyed by sleeper_id, notes about data freshness and lines)."""
    card = load_model_card()
    params = Params(**card["params"])
    notes: list[str] = []

    pg = prepare(data.load_player_games(), scoring)
    tg = data.load_team_games()
    xwalk = data.load_xwalk()

    wk, source_note = week_lines(tg, season, week)
    notes.append(f"Lines: {source_note}")
    last = pg.loc[pg["season"] == season, "week"].max()
    if pd.isna(last) or last < week - 1:
        notes.append(
            f"Stats end at {season} week {0 if pd.isna(last) else int(last)}, so usage from later weeks is "
            "missing. Run the sports_db daily pipeline, then `dbt build` here and `nflm league --refresh`."
        )

    # Sleeper's current team decides who plays where this week (trades, signings)
    players = sleeper.players_frame()
    players = players[players["position"].isin(config.POSITIONS) & players["team"].notna()]
    players = players.merge(xwalk.rename(columns={"gsis_id": "xw_gsis"}), on="sleeper_id", how="left")
    players["gsis_id"] = players["xw_gsis"].fillna(players["gsis_id"])
    history = pg.groupby("gsis_id").agg(
        hist_position=("position", "last"), player_name=("player_name", "last")
    )
    players = players[players["gsis_id"].isin(history.index)].drop_duplicates("gsis_id")

    future = (
        players[["sleeper_id", "gsis_id", "team", "injury_status"]]
        .merge(
            wk[
                [
                    "game_id",
                    "season",
                    "week",
                    "kickoff_utc",
                    "team",
                    "opponent",
                    "is_home",
                    "spread",
                    "total_line",
                    "implied_points",
                    "line_source",
                ]
            ],
            on="team",
            how="inner",
        )
        .join(history, on="gsis_id")
    )
    future["position"] = future.pop("hist_position")
    future[ZERO_COLS] = 0.0
    future["played"] = 0.0
    future["_future"] = True
    # Who is expected to play, from Sleeper's injury status: the injury report, like the
    # backtest's midweek variant. Shares are renormalized over these players below.
    flag = VARIANTS[card.get("live_variant", "midweek")]
    future[flag] = ~future["injury_status"].isin(INACTIVE_STATUSES)
    roles = RoleParams(**card["roles"]) if "roles" in card else None

    priors = season_priors(pg)
    hist = pg[pg["season"] >= season - LIVE_HISTORY_SEASONS]
    if roles is not None:
        # Role curves need each team's earlier games with the same flags and depth tiers as the backtest
        # Only games before this week: rosters for the upcoming week are already loaded, and placeholder
        # rows for them would duplicate this week's live rows (double counting every share)
        status = data.load_player_status()
        status = status[
            (status["season"] >= season - LIVE_HISTORY_SEASONS)
            & (status["kickoff_utc"] < wk["kickoff_utc"].min())
        ]
        hist = add_roster_rows(hist, status)
        depth = data.load_player_depth()[["game_id", "gsis_id", "depth_tier"]]
        future = future.merge(depth, on=["game_id", "gsis_id"], how="left")
    all_rows = pd.concat([hist.assign(_future=False), future], ignore_index=True)
    dupes = all_rows.duplicated(["game_id", "gsis_id"]).sum()
    if dupes:  # a duplicate would be counted twice in every share and role on its team
        raise ValueError(f"{dupes} player-games appear twice in live feature rows")
    feats = add_player_features(all_rows, params, priors)
    if "renorm" in card:
        feats = add_team_usual(feats, pd.concat([tg, wk]), params.hl_team)
    if roles is not None:
        feats = renormalize(feats, flag, Renorm(**card["renorm"]), card["center"])
        feats = apply_roles(feats, flag, roles)
        feats = feats[feats["_future"].astype(bool)]
    else:
        feats = feats[feats["_future"].astype(bool)]
        if "renorm" in card:
            feats = renormalize(feats, flag, Renorm(**card["renorm"]), card["center"])

    other_weeks = tg[~((tg["season"] == season) & (tg["week"] == week))]
    tgf = add_team_features(
        pd.concat([other_weeks, wk.drop(columns=["line_source"])]), params.hl_team, params.coach_k
    )
    train = tgf[
        (tgf["season"] > tgf["season"].min())
        & tgf["pass_attempts"].notna()
        & (tgf["kickoff_utc"] < wk["kickoff_utc"].min())
    ]
    this_week = tgf[(tgf["season"] == season) & (tgf["week"] == week)]
    proj = project(feats, predict_volume(fit_volume_models(train), this_week), scoring)

    proj["blend_w"] = proj["position"].map({p: v["w"] for p, v in card["positions"].items()})
    # Median shift per position (decision 0016); cards from before it have none
    proj["blend_shift"] = proj["position"].map({p: v.get("shift", 0.0) for p, v in card["positions"].items()})
    # Opponent points allowed by position (decision 0018), from every defense's games before this week
    upcoming = wk[["game_id", "team", "kickoff_utc"]].rename(columns={"team": "defense"})
    allowed = matchup.points_allowed(pg[pg["kickoff_utc"] < wk["kickoff_utc"].min()], upcoming)
    weight = card.get("matchup", {}).get("weight", 0.0)
    proj["blend_matchup"] = weight * matchup.player_signal(proj, allowed)
    # Questionable players (decision 0017): Sleeper's status says who is Questionable now; the
    # nflverse injury report in sports_db gives his last practice (Sleeper's practice field is empty)
    status = data.load_player_status()
    if "practice_status" in status:
        proj = proj.merge(
            status[["game_id", "gsis_id", "practice_status"]], on=["game_id", "gsis_id"], how="left"
        )
    else:  # a status table built before 0017: pooled Questionable rates, with a note
        proj["practice_status"] = None
        notes.append(
            "No practice status in int_player_game_status yet: run `dbt build`; Questionable uses pooled rates."
        )
    proj["q_play"], proj["q_mult"] = questionable.factors(proj, card.get("questionable"))
    return proj, notes
