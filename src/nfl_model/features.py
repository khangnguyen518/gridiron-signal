"""Point-in-time features. Every feature for a game uses only rows before it
(sorted by kickoff within player or team), so a game's own stats never leak in.

Recency weighting is exponential in games played: a game h games back counts
half as much as the latest one, where h is the half-life. Shares are ratios of
weighted sums (player targets / team pass attempts), and rates are shrunk
toward the position average with a pseudo-count k:

    rate = (weighted player numerator + k * position_rate) / (weighted denominator + k)
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Params:
    hl_share: float = 4.0  # half-life in games for usage shares
    hl_eff: float = 16.0  # half-life in games for efficiency rates
    hl_team: float = 8.0  # half-life in games for team volume
    k_mult: float = 1.0  # scales every shrinkage pseudo-count
    coach_k: float | None = 2.0  # play-calling under a new head coach: pseudo-count of team history, in games


# Base pseudo-counts, in weighted opportunities, before k_mult
K_TARGETS = 40.0
K_CARRIES = 60.0
K_PASS_ATT = 150.0
K_RZ = 8.0


def lagged_wsum(
    values: pd.Series, groups: pd.Series, half_life: float, step: pd.Series | None = None
) -> pd.Series:
    """Exponentially weighted sum of each group's earlier rows, excluding the
    current row. Weight 1 for the previous game, 0.5 for the game half_life back.
    Rows must already be sorted by time within group.

    step marks rows that count as a game (1) or not (0). A step-0 row is a
    placeholder for a game the player did not play: it adds nothing, does not age
    earlier games, and gets the same features as a game played at that moment."""
    lam = 0.5 ** (1.0 / half_life)
    x = values.fillna(0.0).astype(float).to_numpy()
    st = np.ones(len(x)) if step is None else step.astype(float).to_numpy()
    # i counts games up to and including this row, from 0
    i = pd.Series(st, index=values.index).groupby(groups).cumsum().to_numpy() - 1
    # S_t = x_t + lam^step_t * S_{t-1}, as lam^i * cumsum(x * lam^-i) without a Python loop
    scaled = pd.Series(x * lam ** (-i), index=values.index)
    inclusive = scaled.groupby(groups).cumsum().to_numpy() * lam**i
    return pd.Series((inclusive - x) / lam**st, index=values.index)


def season_priors(pg: pd.DataFrame) -> pd.DataFrame:
    """Position-level rates from seasons strictly before each season (the first
    season falls back to its own rates; it is warm-up only, never evaluated)."""
    totals = (
        pg.groupby(["position", "season"])[
            [
                "targets",
                "receptions",
                "rec_yards",
                "carries",
                "rush_yards",
                "pass_attempts",
                "pass_yards",
                "interceptions",
                "fumbles_lost",
            ]
        ]
        .sum()
        .sort_index()
    )
    prior = totals.groupby(level="position").cumsum().groupby(level="position").shift(1)
    prior = prior.fillna(totals)
    touches = prior["targets"] + prior["carries"] + prior["pass_attempts"]
    out = pd.DataFrame(
        {
            "prior_catch_rate": prior["receptions"] / prior["targets"],
            "prior_yds_per_target": prior["rec_yards"] / prior["targets"],
            "prior_yds_per_carry": prior["rush_yards"] / prior["carries"],
            "prior_fumble_rate": prior["fumbles_lost"] / touches,
        }
    ).reset_index()
    # Passing priors come from QBs for every position, so a trick-play pass by a WR
    # is not judged against the WR's tiny passing sample
    qb = prior.xs("QB", level="position")
    passing = pd.DataFrame(
        {
            "season": qb.index,
            "prior_yds_per_att": (qb["pass_yards"] / qb["pass_attempts"]).to_numpy(),
            "prior_int_rate": (qb["interceptions"] / qb["pass_attempts"]).to_numpy(),
        }
    )
    return out.merge(passing, on="season", how="left")


# Team rates from play-by-play situations: name -> (numerator, denominator, league fallback).
# off_ = this team's offense; def_ = what this team's defense allowed.
TEAM_RATES = {
    "neutral_pass_rate": ("off_neutral_pass_plays", "off_neutral_plays", 0.53),
    "rz_pass_rate": ("off_rz_pass_plays", "off_rz_plays", 0.55),
    "rz_td_rate": ("off_rz_trip_tds", "off_rz_trips", 0.57),
    "rz_pass_td_share": ("off_rz_pass_tds", "off_rz_td_total", 0.58),
    "def_neutral_pass_rate": ("def_neutral_pass_plays", "def_neutral_plays", 0.53),
    "def_rz_td_rate": ("def_rz_trip_tds", "def_rz_trips", 0.57),
    "def_rz_pass_td_share": ("def_rz_pass_tds", "def_rz_td_total", 0.58),
}
# Play-calling rates that follow the head coach (shrunk toward team history when he is new)
COACH_RATES = ("neutral_pass_rate", "rz_pass_rate")


def add_team_features(tg: pd.DataFrame, hl_team: float, coach_k: float | None = None) -> pd.DataFrame:
    """Team recency-weighted per-game volume, play calling and red-zone rates before each game,
    plus the opponent's defensive rates on the same row (opp_def_*). Unplayed games (future rows)
    have null stats and add nothing.

    coach_k: when set, play-calling rates under the current head coach are shrunk toward the
    team's full history with pseudo-count coach_k (in weighted games), so a new coach's own
    games take over quickly. None ignores the coach."""
    tg = tg.sort_values(["team", "kickoff_utc"]).copy()
    played = tg["pass_attempts"].notna().astype(float)
    games = lagged_wsum(played, tg["team"], hl_team)
    for col in ["pass_attempts", "rush_attempts", "pass_tds", "rush_tds", "points_scored"]:
        tg[f"team_avg_{col}"] = lagged_wsum(tg[col], tg["team"], hl_team) / games.replace(0, np.nan)
    tds = tg["team_avg_pass_tds"] + tg["team_avg_rush_tds"]
    tg["team_pass_td_frac"] = (tg["team_avg_pass_tds"] / tds.replace(0, np.nan)).fillna(0.6)

    if "off_plays" not in tg:
        return tg
    tg["off_rz_td_total"] = tg["off_rz_pass_tds"] + tg["off_rz_rush_tds"]
    tg["def_rz_td_total"] = tg["def_rz_pass_tds"] + tg["def_rz_rush_tds"]
    tg["team_plays_pg"] = lagged_wsum(tg["off_plays"], tg["team"], hl_team) / games.replace(0, np.nan)
    tg["team_rz_trips_pg"] = lagged_wsum(tg["off_rz_trips"], tg["team"], hl_team) / games.replace(0, np.nan)
    tg["team_def_rz_trips_pg"] = lagged_wsum(tg["def_rz_trips"], tg["team"], hl_team) / games.replace(
        0, np.nan
    )
    for name, (num, den, fallback) in TEAM_RATES.items():
        n, d = lagged_wsum(tg[num], tg["team"], hl_team), lagged_wsum(tg[den], tg["team"], hl_team)
        rate = (n / d.replace(0, np.nan)).fillna(fallback)
        if coach_k is not None and name in COACH_RATES and "head_coach" in tg:
            era = tg["team"] + "|" + tg["head_coach"].fillna("")
            cn, cd = lagged_wsum(tg[num], era, hl_team), lagged_wsum(tg[den], era, hl_team)
            # pseudo-count in plays: coach_k games of the denominator's usual size
            k = coach_k * (d / games.replace(0, np.nan)).fillna(0)
            rate = ((cn + k * rate) / (cd + k).replace(0, np.nan)).fillna(rate)
        tg[f"team_{name}"] = rate

    defense = [c for c in tg.columns if c.startswith("team_def_")]
    opp = tg[["game_id", "team"] + defense].rename(
        columns={"team": "opponent", **{c: "opp_" + c.removeprefix("team_") for c in defense}}
    )
    return tg.merge(opp, on=["game_id", "opponent"], how="left")


def add_player_features(pg: pd.DataFrame, params: Params, priors: pd.DataFrame) -> pd.DataFrame:
    """Usage shares and shrunk efficiency rates from each player's earlier games."""
    pg = pg.sort_values(["gsis_id", "kickoff_utc"]).copy()
    g = pg["gsis_id"]
    played = pg["played"].astype(float) if "played" in pg else pd.Series(1.0, index=pg.index)

    def ws(col: str, hl: float) -> pd.Series:
        return lagged_wsum(pg[col], g, hl, played)

    hs, he, k = params.hl_share, params.hl_eff, params.k_mult
    pg["prior_games"] = lagged_wsum(played, g, 1e9, played)

    team_pa = ws("team_pass_attempts", hs).replace(0, np.nan)
    team_ra = ws("team_rush_attempts", hs).replace(0, np.nan)
    pg["target_share"] = (ws("targets", hs) / team_pa).fillna(0)
    pg["carry_share"] = (ws("carries", hs) / team_ra).fillna(0)
    pg["att_share"] = (ws("pass_attempts", hs) / team_pa).fillna(0)
    pg["rz_target_share"] = (ws("rz_targets", hs) + K_RZ * k * pg["target_share"]) / (
        ws("team_rz_pass_attempts", hs) + K_RZ * k
    )
    pg["rz_carry_share"] = (ws("rz_carries", hs) + K_RZ * k * pg["carry_share"]) / (
        ws("team_rz_rush_attempts", hs) + K_RZ * k
    )
    pg["points_share"] = (ws("fantasy_points", hs) / ws("team_points", hs).replace(0, np.nan)).fillna(0)

    pg = pg.merge(priors, on=["position", "season"], how="left")
    pg = pg.sort_values(["gsis_id", "kickoff_utc"]).reset_index(drop=True)
    g = pg["gsis_id"]
    played = pg["played"].astype(float) if "played" in pg else pd.Series(1.0, index=pg.index)

    def shrunk(num: str, den: str, prior: str, k_base: float) -> pd.Series:
        kk = k_base * k
        return (lagged_wsum(pg[num], g, he, played) + kk * pg[prior]) / (
            lagged_wsum(pg[den], g, he, played) + kk
        )

    pg["catch_rate"] = shrunk("receptions", "targets", "prior_catch_rate", K_TARGETS)
    pg["yds_per_target"] = shrunk("rec_yards", "targets", "prior_yds_per_target", K_TARGETS)
    pg["yds_per_carry"] = shrunk("rush_yards", "carries", "prior_yds_per_carry", K_CARRIES)
    pg["yds_per_att"] = shrunk("pass_yards", "pass_attempts", "prior_yds_per_att", K_PASS_ATT)
    pg["int_rate"] = shrunk("interceptions", "pass_attempts", "prior_int_rate", K_PASS_ATT)
    return pg
