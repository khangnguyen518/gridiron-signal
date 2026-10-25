"""Opponent points allowed by position, as an adjustment after the blend (decision 0018).

For every player-game, his fantasy points minus his own prior average per game (half-life 6
games) measures how much better or worse he did than usual. A defense's points allowed to a
position is the recency-weighted mean of that over the opposing players at the position in its
earlier games (half-life 8 games, shrunk with 4 pseudo-players of 0), so a defense is not credited
for the offenses it happened to face. Only earlier games enter (features.lagged_wsum).

    blend = w x ours + (1 - w) x Sleeper + shift + weight x points allowed to his position

The weight is a median regression, without an intercept, of the blend's misses on the signal,
fit on earlier seasons: about 0.17, so a defense that allowed 3 points over expectation to TEs
adds about half a point to a TE facing it. Without an intercept it never moves the median
shift's level (decision 0016).
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import QuantileRegressor

from nfl_model.features import lagged_wsum

POSITIONS = ("QB", "RB", "WR", "TE")
HL_PLAYER, HL_DEFENSE, K_PLAYERS = 6, 8, 4


def points_allowed(pg: pd.DataFrame, upcoming: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per defense-game: game_id, defense, and pa_QB ... pa_TE, each defense's points
    allowed over expectation to that position in its earlier games.

    pg: played player-games (game_id, gsis_id, kickoff_utc, position, opponent, fantasy_points).
    upcoming: games with no stats yet (game_id, defense, kickoff_utc), for live projections."""
    p = pg[pg["position"].isin(POSITIONS)].sort_values(["gsis_id", "kickoff_utc"])
    games = lagged_wsum(pd.Series(1.0, index=p.index), p["gsis_id"], HL_PLAYER)
    own = lagged_wsum(p["fantasy_points"], p["gsis_id"], HL_PLAYER) / games
    p = p.assign(over=(p["fantasy_points"] - own).where(games > 0))
    d = p.groupby(["game_id", "opponent", "position"]).agg(over=("over", "sum"), n=("over", "count"))
    d = d.unstack("position", fill_value=0)
    d.columns = [f"{a}_{b}" for a, b in d.columns]
    d = d.reindex(columns=[f"{a}_{pos}" for a in ("over", "n") for pos in POSITIONS], fill_value=0)
    kick = p.groupby(["game_id", "opponent"])["kickoff_utc"].first()
    d = d.join(kick).reset_index().rename(columns={"opponent": "defense"})
    if upcoming is not None and not upcoming.empty:
        d = pd.concat([d, upcoming[["game_id", "defense", "kickoff_utc"]]], ignore_index=True).fillna(0)
    d = d.sort_values(["defense", "kickoff_utc"]).reset_index(drop=True)
    out = d[["game_id", "defense"]].copy()
    for pos in POSITIONS:
        over = lagged_wsum(d[f"over_{pos}"], d["defense"], HL_DEFENSE)
        n = lagged_wsum(d[f"n_{pos}"], d["defense"], HL_DEFENSE)
        out[f"pa_{pos}"] = over / (n + K_PLAYERS)
    return out


def player_signal(rows: pd.DataFrame, allowed: pd.DataFrame) -> pd.Series:
    """Points allowed by each row's opponent to the row's position (0 when unknown)."""
    m = rows[["game_id", "opponent", "position"]].merge(
        allowed, left_on=["game_id", "opponent"], right_on=["game_id", "defense"], how="left"
    )
    pick = np.select(
        [m["position"].eq(pos) for pos in POSITIONS], [m[f"pa_{pos}"] for pos in POSITIONS], np.nan
    )
    return pd.Series(pick, index=rows.index).fillna(0.0)


def fit_weight(miss: pd.Series, signal: pd.Series) -> float:
    """Median-regression slope of the blend's misses on the signal, no intercept."""
    ok = miss.notna() & signal.notna()
    if ok.sum() < 100:
        return 0.0
    m = QuantileRegressor(quantile=0.5, alpha=0.0, fit_intercept=False, solver="highs")
    m.fit(signal[ok].to_numpy()[:, None], miss[ok].to_numpy())
    return round(float(m.coef_[0]), 3)
