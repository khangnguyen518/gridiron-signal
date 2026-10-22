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

VOLUME_SPECS: dict[str, list[str]] = {
    "pass_attempts": ["implied_points", "spread", "team_avg_pass_attempts"],
    "rush_attempts": ["implied_points", "spread", "team_avg_rush_attempts"],
    "pass_tds": ["implied_pass_td_pts"],
    "rush_tds": ["implied_rush_td_pts"],
}


def _volume_inputs(tg: pd.DataFrame) -> pd.DataFrame:
    tg = tg.copy()
    tg["implied_pass_td_pts"] = tg["implied_points"] * tg["team_pass_td_frac"]
    tg["implied_rush_td_pts"] = tg["implied_points"] * (1 - tg["team_pass_td_frac"])
    return tg


def fit_volume_models(tg_train: pd.DataFrame) -> dict[str, LinearRegression]:
    """One linear model per team volume stat, on played team-games with history."""
    tg_train = _volume_inputs(tg_train)
    models = {}
    for target, cols in VOLUME_SPECS.items():
        rows = tg_train.dropna(subset=cols + [target])
        models[target] = LinearRegression().fit(rows[cols], rows[target])
    return models


def predict_volume(models: dict[str, LinearRegression], tg: pd.DataFrame) -> pd.DataFrame:
    tg = _volume_inputs(tg)
    out = tg[["game_id", "team"]].copy()
    for target, cols in VOLUME_SPECS.items():
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
