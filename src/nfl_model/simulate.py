"""Game simulation: a distribution of fantasy points for every player, with the
correlations a real game creates (a QB and his receivers share touchdowns, a
blowout changes everyone's volume).

Each of n draws plays every game once:

    game        home margin ~ Normal(spread, sd_margin), total ~ Normal(total, sd_total)
                team points P = (total +/- margin) / 2, scoring factor F = P / implied points
    script      pass attempts x exp(-script_pass x margin_dev / 7), rush attempts x exp(+script_rush x ...)
                (a team that falls behind throws more and runs less)
    usage       targets and carries split by a Dirichlet draw around each player's share
                (concentration kappa), then Poisson counts
    efficiency  catches ~ Binomial(targets, catch rate); yards = n x mean x F^eta + sqrt(n) x sd x Normal
    touchdowns  receiving and rushing TDs ~ Poisson(team TDs x F x red-zone share)
    QB          passing yards and TDs are his attempt share of the team's receiving yards and
                receiving TDs, so a QB and his receivers rise and fall together
    points      the league's scoring on every simulated stat line

A pseudo-player per team ("other") takes the usage no listed player holds, so team
totals stay right. Draws are rescaled per player to the projection the caller uses
(ours or the blend): the simulation supplies the shape and the correlations, the
projection supplies the center.
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from nfl_model.scoring import DEFAULT_SCORING, POSITION_BONUSES, STAT_KEYS

# Measured on 2012-2017 (docs/model.md, "Game simulation")
SD_MARGIN = 13.2  # actual home margin minus closing spread
SD_TOTAL = 13.4  # actual total minus closing total
SD_PER_RECEPTION = 10.3  # yards on a completed pass
SD_PER_CARRY = 6.3  # yards on a designed run
# The pseudo-player "other" uses league-average efficiency
OTHER = {"catch_rate": 0.65, "yds_per_target": 7.4, "yds_per_carry": 4.0}
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)


@dataclass(frozen=True)
class SimParams:
    kappa: float = 50.0  # Dirichlet concentration of usage around shares (higher = steadier)
    eta: float = 0.5  # how strongly yards per play rise with the team's scoring factor
    yds_sd_mult: float = 1.0  # scales per-play yardage noise
    script_pass: float = (
        0.0  # fitted: log pass attempts per 7 points of margin deviation (sign: trailing -> more)
    )
    script_rush: float = 0.0  # fitted: log rush attempts per 7 points of margin deviation (leading -> more)

    def as_dict(self) -> dict:
        return asdict(self)


def fit_script(team_rows: pd.DataFrame) -> tuple[float, float]:
    """Slopes of log(actual / predicted) pass and rush attempts on (margin - spread) / 7, from
    played team-games that carry volume predictions. Returned as positive magnitudes."""
    t = team_rows.dropna(subset=["pass_attempts", "team_pass_attempts_hat", "margin", "spread"])
    t = t[
        (t["team_pass_attempts_hat"] > 0)
        & (t["team_rush_attempts_hat"] > 0)
        & (t["pass_attempts"] > 0)
        & (t["rush_attempts"] > 0)
    ]
    x = ((t["margin"] - t["spread"]) / 7).to_numpy()
    yp = np.log(t["pass_attempts"] / t["team_pass_attempts_hat"]).to_numpy()
    yr = np.log(t["rush_attempts"] / t["team_rush_attempts_hat"]).to_numpy()
    bp = np.polyfit(x, yp, 1)[0]
    br = np.polyfit(x, yr, 1)[0]
    return float(-bp), float(br)


def _group_sum(values: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Sum rows (axis 0) within contiguous groups beginning at `starts`."""
    return np.add.reduceat(values, starts, axis=0)


def simulate(
    rows: pd.DataFrame,
    params: SimParams,
    n: int = 1000,
    scoring: dict[str, float] | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Simulated fantasy points, shape (len(rows), n), in the order of `rows`.
    rows: projected player rows (model.project output) for whole team-games."""
    scoring = scoring or DEFAULT_SCORING
    rng = np.random.default_rng(seed)
    r = rows.reset_index(drop=True).copy()
    r["_row"] = np.arange(len(r))

    # Teams and games
    teams = r.drop_duplicates(["game_id", "team"])[
        [
            "game_id",
            "team",
            "is_home",
            "implied_points",
            "spread",
            "total_line",
            "team_pass_attempts_hat",
            "team_rush_attempts_hat",
            "team_pass_tds_hat",
            "team_rush_tds_hat",
        ]
    ].reset_index(drop=True)
    teams["t"] = np.arange(len(teams))
    games = {g: i for i, g in enumerate(teams["game_id"].unique())}
    gi = teams["game_id"].map(games).to_numpy()
    sign = np.where(teams["is_home"].astype(bool), 1.0, -1.0)[:, None]
    margin_dev = rng.normal(0, SD_MARGIN, (len(games), n))[gi]
    total_dev = rng.normal(0, SD_TOTAL, (len(games), n))[gi]
    implied = teams["implied_points"].to_numpy(float)[:, None]
    points = np.maximum(implied + (total_dev + sign * margin_dev) / 2, 0.0)
    factor = np.clip(points / np.maximum(implied, 1.0), 0.0, 4.0)
    md7 = sign * margin_dev / 7
    pass_att = teams["team_pass_attempts_hat"].to_numpy(float)[:, None] * np.exp(-params.script_pass * md7)
    rush_att = teams["team_rush_attempts_hat"].to_numpy(float)[:, None] * np.exp(params.script_rush * md7)
    pass_td_mean = teams["team_pass_tds_hat"].to_numpy(float)[:, None] * factor
    rush_td_mean = teams["team_rush_tds_hat"].to_numpy(float)[:, None] * factor

    # Players plus one "other" row per team, sorted by team for group sums
    r = r.merge(teams[["game_id", "team", "t"]], on=["game_id", "team"])
    sums = r.groupby("t")[["target_share", "carry_share", "rz_target_share", "rz_carry_share"]].sum()
    other = pd.DataFrame(
        {
            "t": sums.index,
            "position": "OTHER",
            "target_share": (1 - sums["target_share"]).clip(lower=0.03).to_numpy(),
            "carry_share": (1 - sums["carry_share"]).clip(lower=0.03).to_numpy(),
            "rz_target_share": (1 - sums["rz_target_share"]).clip(lower=0.03).to_numpy(),
            "rz_carry_share": (1 - sums["rz_carry_share"]).clip(lower=0.03).to_numpy(),
            "att_share": 0.0,
            "int_rate": 0.0,
            "prior_fumble_rate": 0.0,
            "catch_rate": OTHER["catch_rate"],
            "yds_per_target": OTHER["yds_per_target"],
            "yds_per_carry": OTHER["yds_per_carry"],
            "_row": -1,
        }
    )
    allr = pd.concat([r, other], ignore_index=True).sort_values(["t", "_row"], kind="stable")
    allr = allr.reset_index(drop=True)
    t = allr["t"].to_numpy()
    starts = np.flatnonzero(np.r_[True, t[1:] != t[:-1]])

    def col(name: str) -> np.ndarray:
        # Clipped: nflverse stat corrections leave a few slightly negative shares
        return np.clip(allr[name].fillna(0.0).to_numpy(float), 0.0, None)[:, None]

    def dirichlet_split(share: np.ndarray) -> np.ndarray:
        """Per-row usage multipliers: a Dirichlet draw over the team's shares, scaled so
        each row's mean share is unchanged."""
        total = np.maximum(_group_sum(share, starts), 1e-9)
        w = share / total[t]
        g = rng.gamma(np.maximum(params.kappa * w, 1e-6), 1.0, (len(allr), n))
        return g / _group_sum(g, starts)[t] * total[t]

    tgt_share, car_share = col("target_share"), col("carry_share")
    f = factor[t]
    targets = rng.poisson(pass_att[t] * dirichlet_split(tgt_share))
    receptions = rng.binomial(targets, np.clip(col("catch_rate"), 0, 1))
    ypr = col("yds_per_target") / np.maximum(col("catch_rate"), 0.05)
    sd = params.yds_sd_mult
    rec_yards = receptions * ypr * f**params.eta + np.sqrt(
        receptions
    ) * SD_PER_RECEPTION * sd * rng.standard_normal(receptions.shape)
    rec_tds = rng.poisson(pass_td_mean[t] * col("rz_target_share"))

    carries = rng.poisson(rush_att[t] * dirichlet_split(car_share))
    rush_yards = carries * col("yds_per_carry") * f**params.eta + np.sqrt(carries) * SD_PER_CARRY * sd * (
        rng.standard_normal(carries.shape)
    )
    rush_tds = rng.poisson(rush_td_mean[t] * col("rz_carry_share"))

    att_share = col("att_share")
    team_rec_yards = _group_sum(rec_yards, starts)[t]
    team_rec_tds = _group_sum(rec_tds, starts)[t]
    pass_yards = att_share * team_rec_yards
    pass_tds = rng.binomial(team_rec_tds.astype(np.int64), np.clip(att_share, 0, 1))
    interceptions = rng.poisson(pass_att[t] * att_share * col("int_rate"))
    fumbles = rng.poisson((targets + carries) * col("prior_fumble_rate"))

    stats = {
        "pass_yards": pass_yards,
        "pass_tds": pass_tds,
        "interceptions": interceptions,
        "rush_yards": rush_yards,
        "rush_tds": rush_tds,
        "receptions": receptions,
        "rec_yards": rec_yards,
        "rec_tds": rec_tds,
        "fumbles_lost": fumbles,
    }
    pts = np.zeros((len(allr), n))
    for col_name, arr in stats.items():
        pts += arr * scoring.get(STAT_KEYS[col_name], 0.0)
    position = allr["position"].to_numpy()[:, None]
    for key, (pos, col_name) in POSITION_BONUSES.items():
        if scoring.get(key):
            pts += np.where(position == pos, stats[col_name] * scoring[key], 0.0)

    keep = allr["_row"].to_numpy() >= 0
    out = np.empty((len(r), n))
    out[allr.loc[keep, "_row"].to_numpy()] = pts[keep]
    return out


def rescale(draws: np.ndarray, center: np.ndarray) -> np.ndarray:
    """Scales each row's draws so their mean equals `center` (the projection in use)."""
    mean = draws.mean(axis=1, keepdims=True)
    ratio = np.where(mean > 0.1, np.asarray(center, float)[:, None] / np.maximum(mean, 0.1), 1.0)
    return draws * ratio


def stretch_tails(
    draws: np.ndarray, center: np.ndarray, positions: np.ndarray, tails: dict[str, list[float]] | None
) -> np.ndarray:
    """Per-position stretch of each player's downside and upside around his projection:
    center + d_low x (draw - center) below it, d_high x (draw - center) above it. Monotone, so
    every player's rank in each simulated game, and so the correlations, stay the same.
    Tuned on 2016-2018 (sim_backtest.py); QBs bust more often than the simulation alone says."""
    if not tails:
        return draws
    c = np.asarray(center, float)[:, None]
    lo = np.array([tails.get(p, [1.0, 1.0])[0] for p in positions])[:, None]
    hi = np.array([tails.get(p, [1.0, 1.0])[1] for p in positions])[:, None]
    dev = draws - c
    return c + np.where(dev < 0, lo, hi) * dev


RESID_LEVELS = np.linspace(0.01, 0.99, 99)
CENTER_BIN_LEVELS = [0.2, 0.4, 0.6, 0.8]


def residual_table(rows: pd.DataFrame, center: str = "opp_points") -> dict:
    """Historical misses (actual minus projection) at 99 percentiles, by position and
    projection quintile: the empirical side of each player's range."""
    edges = np.quantile(rows[center], CENTER_BIN_LEVELS).tolist()
    bins = np.digitize(rows[center], edges)
    resid = (rows["fantasy_points"] - rows[center]).to_numpy()
    table: dict[str, list[list[float]]] = {}
    for pos in rows["position"].unique():
        m = (rows["position"] == pos).to_numpy()
        table[pos] = [
            np.quantile(resid[m & (bins == b)], RESID_LEVELS).round(3).tolist() for b in range(len(edges) + 1)
        ]
    return {"edges": edges, "levels": RESID_LEVELS.round(3).tolist(), "resid": table}


def mix_with_residuals(
    draws: np.ndarray,
    center: np.ndarray,
    positions: np.ndarray,
    table: dict | None,
    weights: dict[str, float] | None,
) -> np.ndarray:
    """Each player's draw at percentile u becomes w x draw + (1 - w) x (center + historical miss
    at u). The range is then the average of the simulation's and history's quantiles, and
    each player keeps his rank in every simulated game, so correlations carry over."""
    if not table or not weights:
        return draws
    n = draws.shape[1]
    u = (np.argsort(np.argsort(draws, axis=1), axis=1) + 0.5) / n
    c = np.asarray(center, float)
    bins = np.digitize(c, table["edges"])
    levels = np.asarray(table["levels"])
    out = draws.astype(float).copy()
    for i, pos in enumerate(positions):
        w = weights.get(pos)
        if w is None or pos not in table["resid"]:
            continue
        hist = c[i] + np.interp(u[i], levels, np.asarray(table["resid"][pos][bins[i]]))
        out[i] = w * draws[i] + (1 - w) * hist
    return out


def quantile_frame(draws: np.ndarray, quantiles: tuple[float, ...] = QUANTILES) -> pd.DataFrame:
    q = np.quantile(draws, quantiles, axis=1).T
    return pd.DataFrame(q, columns=[f"p{round(x * 100):02d}" for x in quantiles])
