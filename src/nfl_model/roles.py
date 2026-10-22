"""Roles (WR1, WR2, RB1, ...) and how each team spreads the ball among them.

Each week, a team's expected-to-play WRs, TEs and RBs are ranked within their position: by
depth chart tier first (starters before backups, rule "depth") or by recent share alone (rule
"share"), then by recent share. That rank is the player's role this week.

A team's role curve is the share each role actually got in its earlier games, recency-weighted:
an offense that feeds its WR1 has a high WR1 target curve, a spread offense a flat one; a
workhorse backfield has a high RB1 carry curve, a committee a low one. Each player's share is
then pulled toward his team's curve for his role:

    share' = (n x share + k x curve) / (n + k)

where n is his recency-weighted games played (`share_games`) and k is tuned. A player with
little history, or one who just moved up the depth chart, leans on his role; a veteran with a
steady role barely moves. Red-zone shares scale with their base share.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nfl_model.features import lagged_wsum

ROLE_POSITIONS = ("WR", "TE", "RB")
# The share that orders players within a position, and the curves each position gets
RANK_SHARE = {"WR": "target_share", "TE": "target_share", "RB": "carry_share"}
UNLISTED_TIER = 9  # not on the depth chart: after every listed player


@dataclass(frozen=True)
class RoleParams:
    rule: str = "depth"  # "depth": depth tier, then share; "share": share only
    hl_role: float = 8.0  # half-life in team games for role curves
    k_target: float = 0.0  # pull of target shares toward the role curve, in games
    k_carry: float = 0.0  # pull of carry shares toward the role curve, in games


def assign_roles(feats: pd.DataFrame, flag: str, rule: str) -> pd.Series:
    """Role rank (1 = first) within team-game and position among players expected to play;
    NaN for everyone else."""
    eligible = feats[flag].astype(bool) & feats["position"].isin(ROLE_POSITIONS)
    f = feats.loc[eligible, ["game_id", "team", "position", "target_share", "carry_share"]].copy()
    f["rank_share"] = np.where(f["position"] == "RB", f["carry_share"], f["target_share"])
    tier = feats.loc[eligible, "depth_tier"] if "depth_tier" in feats else pd.Series(np.nan, index=f.index)
    f["tier"] = tier.fillna(UNLISTED_TIER) if rule == "depth" else 0
    f = f.sort_values(
        ["game_id", "team", "position", "tier", "rank_share"], ascending=[True, True, True, True, False]
    )
    role = f.groupby(["game_id", "team", "position"]).cumcount() + 1
    return role.reindex(feats.index)


def add_role_curves(feats: pd.DataFrame, role: pd.Series, hl_role: float) -> pd.DataFrame:
    """curve_target and curve_carry: the share this team's same role got in its earlier games."""
    f = feats.assign(role=role)
    team_att = f.groupby(["game_id", "team"])[["team_pass_attempts", "team_rush_attempts"]].transform("max")
    f["real_target"] = f["targets"] / team_att["team_pass_attempts"].replace(0, np.nan)
    f["real_carry"] = f["carries"] / team_att["team_rush_attempts"].replace(0, np.nan)
    hist = f[f["role"].notna()][
        ["game_id", "team", "position", "role", "kickoff_utc", "real_target", "real_carry"]
    ]
    hist = hist.sort_values(["team", "position", "role", "kickoff_utc"]).reset_index()
    key = hist["team"] + "|" + hist["position"] + "|" + hist["role"].astype(int).astype(str)
    done = hist["real_target"].notna().astype(float)  # unplayed (future) games add nothing
    games = lagged_wsum(done, key, hl_role, done)
    for col, out in [("real_target", "curve_target"), ("real_carry", "curve_carry")]:
        hist[out] = lagged_wsum(hist[col], key, hl_role, done) / games.replace(0, np.nan)
    curves = hist.set_index("index")[["curve_target", "curve_carry"]]
    return feats.join(curves).assign(role=role)


def shrink_to_roles(feats: pd.DataFrame, params: RoleParams) -> pd.DataFrame:
    """Pull each WR, TE and RB share toward his team's curve for his role this week."""
    f = feats.copy()
    n = f["share_games"].fillna(0)
    for share, rz, curve, k in [
        ("target_share", "rz_target_share", "curve_target", params.k_target),
        ("carry_share", "rz_carry_share", "curve_carry", params.k_carry),
    ]:
        if k <= 0:
            continue
        ok = f["role"].notna() & f[curve].notna()
        if share == "carry_share":
            ok &= f["position"] == "RB"
        new = (n * f[share] + k * f[curve]) / (n + k)
        ratio = (new / f[share].replace(0, np.nan)).fillna(1.0)
        f.loc[ok, rz] = f.loc[ok, rz] * ratio[ok].clip(0, 5)
        f.loc[ok, share] = new[ok]
    return f


def apply_roles(feats: pd.DataFrame, flag: str, params: RoleParams) -> pd.DataFrame:
    """Roles, team role curves and the pull toward them, in one step. Needs every team's
    earlier games in `feats` for the curves."""
    curves = add_role_curves(feats, assign_roles(feats, flag, params.rule), params.hl_role)
    return shrink_to_roles(curves, params)
