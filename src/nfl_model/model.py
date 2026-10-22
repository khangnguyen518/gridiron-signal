"""The two projections.

Points share (baseline):
    points = team implied points x player's recent share of team points scored

Opportunity (top-down):
    team volume  = f(implied points, spread, team's recent volume)   [fit on past seasons]
    player usage = team volume x player's recent share
    player stats = usage x shrunk efficiency, TDs = team TDs x red-zone share
    points       = league scoring applied to the projected stat line
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from nfl_model.scoring import fantasy_points

# Red-zone inputs: implied points scaled by the team's and the opponent defense's red-zone rates
RED_ZONE_INPUTS = [
    "implied_x_rz_td_rate",
    "implied_x_opp_def_rz_td_rate",
    "implied_x_rz_pass_td_share",
    "implied_x_opp_def_rz_pass_td_share",
    "implied_x_rz_pass_rate",
]
# Per target, the inputs chosen on 2013-2018 player MAE (docs/backtest.md, "Team style and red zone").
# Rushing gains from play calling (the team's neutral pass rate under its head coach, plays per game,
# and the opponent defense's neutral pass rate faced) and red-zone rates. Passing did not: it keeps
# the lines-only inputs.
VOLUME_SPECS: dict[str, list[str]] = {
    "pass_attempts": ["implied_points", "spread", "team_avg_pass_attempts"],
    "rush_attempts": [
        "implied_points",
        "spread",
        "team_avg_rush_attempts",
        "team_neutral_pass_rate",
        "team_plays_pg",
        "opp_def_neutral_pass_rate",
    ],
    "pass_tds": ["implied_pass_td_pts"],
    "rush_tds": ["implied_rush_td_pts", *RED_ZONE_INPUTS],
}
# The inputs before 2026-10-23, for comparisons
LINES_ONLY_SPECS: dict[str, list[str]] = {
    "pass_attempts": ["implied_points", "spread", "team_avg_pass_attempts"],
    "rush_attempts": ["implied_points", "spread", "team_avg_rush_attempts"],
    "pass_tds": ["implied_pass_td_pts"],
    "rush_tds": ["implied_rush_td_pts"],
}


def _volume_inputs(tg: pd.DataFrame) -> pd.DataFrame:
    """Derived inputs: implied points split by pass/run touchdown mix, and implied points scaled by
    red-zone rates (team offense and opponent defense) where those features exist."""
    tg = tg.copy()
    tg["implied_pass_td_pts"] = tg["implied_points"] * tg["team_pass_td_frac"]
    tg["implied_rush_td_pts"] = tg["implied_points"] * (1 - tg["team_pass_td_frac"])
    if "team_rz_td_rate" in tg:
        tg["implied_x_rz_td_rate"] = tg["implied_points"] * tg["team_rz_td_rate"]
        tg["implied_x_opp_def_rz_td_rate"] = tg["implied_points"] * tg["opp_def_rz_td_rate"]
        tg["implied_x_rz_pass_td_share"] = tg["implied_points"] * tg["team_rz_pass_td_share"]
        tg["implied_x_opp_def_rz_pass_td_share"] = tg["implied_points"] * tg["opp_def_rz_pass_td_share"]
        tg["implied_x_rz_pass_rate"] = tg["implied_points"] * tg["team_rz_pass_rate"]
    return tg


def fit_volume_models(
    tg_train: pd.DataFrame, specs: dict[str, list[str]] | None = None
) -> dict[str, LinearRegression]:
    """One linear model per team volume stat, on played team-games with history."""
    specs = specs or VOLUME_SPECS
    tg_train = _volume_inputs(tg_train)
    models = {}
    for target, cols in specs.items():
        rows = tg_train.dropna(subset=cols + [target])
        models[target] = LinearRegression().fit(rows[cols], rows[target])
    return models


def predict_volume(
    models: dict[str, LinearRegression], tg: pd.DataFrame, specs: dict[str, list[str]] | None = None
) -> pd.DataFrame:
    specs = specs or VOLUME_SPECS
    tg = _volume_inputs(tg)
    out = tg[["game_id", "team"]].copy()
    for target, cols in specs.items():
        ok = tg[cols].notna().all(axis=1)
        pred = pd.Series(np.nan, index=tg.index)
        if ok.any():
            pred[ok] = models[target].predict(tg.loc[ok, cols])
        out[f"team_{target}_hat"] = pred.clip(lower=0)
    return out


def project(pg: pd.DataFrame, volume: pd.DataFrame, scoring: dict[str, float] | None = None) -> pd.DataFrame:
    """Adds projected stat columns (*_hat), opp_points and share_points to player rows
    that already carry features from features.add_player_features."""
    df = pg.merge(volume, on=["game_id", "team"], how="left")
    pa, ra = df["team_pass_attempts_hat"], df["team_rush_attempts_hat"]
    ptd, rtd = df["team_pass_tds_hat"], df["team_rush_tds_hat"]

    targets = pa * df["target_share"]
    carries = ra * df["carry_share"]
    att = pa * df["att_share"]
    stats = pd.DataFrame(
        {
            "position": df["position"],
            "targets": targets,
            "receptions": targets * df["catch_rate"],
            "rec_yards": targets * df["yds_per_target"],
            "rec_tds": ptd * df["rz_target_share"],
            "carries": carries,
            "rush_yards": carries * df["yds_per_carry"],
            "rush_tds": rtd * df["rz_carry_share"],
            "pass_attempts": att,
            "pass_yards": att * df["yds_per_att"],
            "pass_tds": ptd * df["att_share"],
            "interceptions": att * df["int_rate"],
            "fumbles_lost": (targets + carries) * df["prior_fumble_rate"],
        }
    )
    for col in stats.columns.drop("position"):
        df[f"{col}_hat"] = stats[col]
    df["opp_points"] = fantasy_points(stats, scoring)
    df["share_points"] = df["implied_points"] * df["points_share"]
    return df
