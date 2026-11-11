"""Kickers and team defenses as stat lines from the betting lines (decision 0021).

Each team-game gets an expected stat line for its kicker slot and its defense, scored with the
league's settings like every other position (decision 0007):

Defense
    points allowed  opponent implied points + a residual drawn from earlier seasons' misses
                    (as Sleeper scores it: minus the opponent's defensive and special-teams TDs).
                    Points-allowed brackets are not linear, so expected bracket points average
                    the bracket over the residual distribution.
    counts          sacks, interceptions, fumble recoveries, forced fumbles, defensive and
                    special-teams TDs, safeties, blocked kicks, special-teams fumble recoveries:
                    Poisson regressions on opponent implied points, own spread, the defense's
                    recent rate and the opponent offense's recent rate allowed (half-life 8 games,
                    earlier games only).
Kicker (the team's kicker slot)
    attempts        field goal attempts in each of Sleeper's distance bands and extra point
                    attempts: Poisson regressions on the team's implied points and spread.
    makes           league make rate per band from earlier seasons; misses are the rest.

Fit on every earlier season with lines (2010 onward). Range draws use the same pieces: residual
quantiles for points allowed, Poisson counts and binomial makes.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import PoissonRegressor

from nfl_model.features import lagged_wsum

HL = 8
DEF_COUNTS = {  # stat column -> Sleeper scoring key
    "sacks": "sack",
    "ints": "int",
    "fum_rec": "fum_rec",
    "ff": "ff",
    "def_td": "def_td",
    "safeties": "safe",
    "blk_kick": "blk_kick",
    "st_fum_rec": "st_fum_rec",
}
BANDS = ["0_19", "20_29", "30_39", "40_49", "50p"]
PA_BRACKETS = [
    (-999, 0, "pts_allow_0"),
    (1, 6, "pts_allow_1_6"),
    (7, 13, "pts_allow_7_13"),
    (14, 20, "pts_allow_14_20"),
    (21, 27, "pts_allow_21_27"),
    (28, 34, "pts_allow_28_34"),
    (35, 999, "pts_allow_35p"),
]
LEVELS = np.linspace(0.005, 0.995, 100)


def _league_prior(df: pd.DataFrame, col: str) -> pd.Series:
    """League average of `col` per game over games that kicked off before each row (games at the
    same kickoff time excluded), so the shrinkage target never sees the row's own or later games."""
    played = df[df["played"].astype(bool)]
    by_time = played.groupby("kickoff_utc")[col].agg(["sum", "count"]).sort_index()
    before = by_time.cumsum().shift(1)
    mean = (before["sum"] / before["count"]).reindex(df["kickoff_utc"].sort_values().unique()).ffill()
    return df["kickoff_utc"].map(mean).fillna(0.0)


def _recent_rate(df: pd.DataFrame, key: str, cols: list[str]) -> pd.DataFrame:
    """Recency-weighted per-game average of `cols` over each key's earlier games, shrunk toward
    the league average of earlier games with 4 pseudo-games."""
    d = df.sort_values([key, "kickoff_utc"])
    n = lagged_wsum(pd.Series(d["played"].astype(float), index=d.index), d[key], HL, step=d["played"])
    out = pd.DataFrame(index=d.index)
    for c in cols:
        prior = _league_prior(df, c).reindex(d.index)
        s = lagged_wsum(d[c].fillna(0.0), d[key], HL, step=d["played"])
        out[c] = (s + 4 * prior) / (n + 4)
    return out.reindex(df.index)


def defense_rows(dg: pd.DataFrame, tg: pd.DataFrame, upcoming: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per team-game with lines (played games from dg, plus upcoming games with no stats):
    opponent implied points, spread, and recent rates for the defense and the opponent offense."""
    lines = tg[
        [
            "game_id",
            "team",
            "opponent",
            "season",
            "week",
            "kickoff_utc",
            "spread",
            "total_line",
            "implied_points",
        ]
    ]
    rows = lines.merge(
        dg.drop(columns=["season", "week", "kickoff_utc", "opponent"], errors="ignore"),
        on=["game_id", "team"],
        how="inner",
    )
    rows["played"] = 1.0
    if upcoming is not None and not upcoming.empty:
        up = upcoming[
            [
                "game_id",
                "team",
                "opponent",
                "season",
                "week",
                "kickoff_utc",
                "spread",
                "total_line",
                "implied_points",
            ]
        ]
        rows = pd.concat([rows, up.assign(played=0.0)], ignore_index=True)
    rows["opp_implied"] = rows["total_line"] - rows["implied_points"]
    own = _recent_rate(rows, "team", list(DEF_COUNTS))
    rows[[f"rate_{c}" for c in DEF_COUNTS]] = own.to_numpy()
    # What each offense has given up to defenses: the same counts, keyed by the opponent
    allowed = _recent_rate(rows, "opponent", list(DEF_COUNTS))
    rows[[f"opp_allows_{c}" for c in DEF_COUNTS]] = allowed.to_numpy()
    return rows


def kicker_rows(kg: pd.DataFrame, tg: pd.DataFrame, upcoming: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per team-game (the team's kicker slot): attempts and makes summed over the team's
    kickers that game, with the team's lines."""
    cols = [f"fga_{b}" for b in BANDS] + [f"fgm_{b}" for b in BANDS] + ["fgmiss", "xpa", "xpm", "xpmiss"]
    team = kg.groupby(["game_id", "team"])[cols].sum().reset_index()
    lines = tg[
        [
            "game_id",
            "team",
            "opponent",
            "season",
            "week",
            "kickoff_utc",
            "spread",
            "total_line",
            "implied_points",
        ]
    ]
    played = lines[tg["points_scored"].notna()] if "points_scored" in tg else lines
    rows = played.merge(team, on=["game_id", "team"], how="left").fillna({c: 0.0 for c in cols})
    rows["played"] = 1.0
    if upcoming is not None and not upcoming.empty:
        rows = pd.concat([rows, upcoming[lines.columns].assign(played=0.0)], ignore_index=True)
    return rows


def _poisson(X: pd.DataFrame, y: pd.Series) -> dict:
    m = PoissonRegressor(alpha=1e-4, max_iter=1000).fit(X.to_numpy(), y.to_numpy())
    return {"cols": list(X.columns), "coef": [float(c) for c in m.coef_], "intercept": float(m.intercept_)}


def _predict(model: dict, rows: pd.DataFrame) -> np.ndarray:
    X = rows[model["cols"]].to_numpy(dtype=float)
    return np.exp(model["intercept"] + X @ np.array(model["coef"]))


def _def_features(c: str) -> list[str]:
    return ["opp_implied", "spread", f"rate_{c}", f"opp_allows_{c}"]


def fit_defense(rows: pd.DataFrame) -> dict:
    """Fit on played rows with lines: one Poisson model per count, residual quantiles for points allowed."""
    r = rows[rows["played"].eq(1) & rows["opp_implied"].notna()]
    resid = r["pts_allowed"] - r["opp_implied"]
    return {
        "counts": {c: _poisson(r[_def_features(c)], r[c]) for c in DEF_COUNTS},
        "pa_resid_quantiles": [float(q) for q in np.quantile(resid, LEVELS)],
        "n": len(r),
    }


def fit_kicker(rows: pd.DataFrame) -> dict:
    r = rows[rows["played"].eq(1) & rows["implied_points"].notna()]
    X = r[["implied_points", "spread"]]
    fit = {"attempts": {}, "make_rate": {}, "n": len(r)}
    for b in BANDS:
        fit["attempts"][f"fga_{b}"] = _poisson(X, r[f"fga_{b}"])
        fit["make_rate"][b] = float(r[f"fgm_{b}"].sum() / max(r[f"fga_{b}"].sum(), 1))
    fit["attempts"]["xpa"] = _poisson(X, r["xpa"])
    fit["make_rate"]["xp"] = float(r["xpm"].sum() / max(r["xpa"].sum(), 1))
    return fit


def pa_points(pts: np.ndarray, scoring: dict[str, float]) -> np.ndarray:
    """League points for points allowed, by bracket (pts rounded to whole points)."""
    p = np.round(pts)
    out = np.zeros_like(p, dtype=float)
    for lo, hi, key in PA_BRACKETS:
        out[(p >= lo) & (p <= hi)] = scoring.get(key, 0.0)
    return out


def project_defense(rows: pd.DataFrame, fit: dict, scoring: dict[str, float]) -> pd.DataFrame:
    """Expected stat line and league points per defense row."""
    out = pd.DataFrame(index=rows.index)
    for c in DEF_COUNTS:
        out[c] = _predict(fit["counts"][c], rows)
    q = np.array(fit["pa_resid_quantiles"])
    pa = np.clip(rows["opp_implied"].to_numpy()[:, None] + q[None, :], 0, None)
    out["pts_allowed"] = pa.mean(axis=1)
    out["pa_points"] = pa_points(pa, scoring).mean(axis=1)
    out["points"] = out["pa_points"] + sum(out[c] * scoring.get(k, 0.0) for c, k in DEF_COUNTS.items())
    return out


def project_kicker(rows: pd.DataFrame, fit: dict, scoring: dict[str, float]) -> pd.DataFrame:
    out = pd.DataFrame(index=rows.index)
    misses = 0.0
    for b in BANDS:
        att = _predict(fit["attempts"][f"fga_{b}"], rows)
        p = fit["make_rate"][b]
        out[f"fgm_{b}"] = att * p
        misses = misses + att * (1 - p)
    out["fgmiss"] = misses
    xpa = _predict(fit["attempts"]["xpa"], rows)
    out["xpm"] = xpa * fit["make_rate"]["xp"]
    out["xpmiss"] = xpa * (1 - fit["make_rate"]["xp"])
    keys = [f"fgm_{b}" for b in BANDS] + ["fgmiss", "xpm", "xpmiss"]
    out["points"] = sum(out[k] * scoring.get(k, 0.0) for k in keys)
    return out


def actual_defense_points(rows: pd.DataFrame, scoring: dict[str, float]) -> pd.Series:
    """League points from a played defense row's stat line (the same definitions as Sleeper)."""
    pts = pa_points(rows["pts_allowed"].to_numpy(dtype=float), scoring)
    return pd.Series(pts, index=rows.index) + sum(
        rows[c] * scoring.get(k, 0.0) for c, k in DEF_COUNTS.items()
    )


def actual_kicker_points(rows: pd.DataFrame, scoring: dict[str, float]) -> pd.Series:
    keys = [f"fgm_{b}" for b in BANDS] + ["fgmiss", "xpm", "xpmiss"]
    return sum(rows[k] * scoring.get(k, 0.0) for k in keys)


def stretch(draws: np.ndarray, factor: float) -> np.ndarray:
    """Widen (factor > 1) or narrow each row's draws around its median. Independent counts miss
    that a unit's stats move together, so the factor is calibrated on earlier seasons."""
    med = np.median(draws, axis=1, keepdims=True)
    return med + factor * (draws - med)


def calibrate_stretch(draws: np.ndarray, actual: np.ndarray, target: float = 0.8) -> float:
    """Stretch factor whose 10-90 range covers `target` of the actual outcomes."""
    grid = np.round(np.arange(0.5, 2.51, 0.05), 2)
    cov = []
    for f in grid:
        q = np.quantile(stretch(draws, f), [0.1, 0.9], axis=1)
        cov.append(np.mean((actual >= q[0]) & (actual <= q[1])))
    return float(grid[int(np.argmin(np.abs(np.array(cov) - target)))])


def draw_defense(
    rows: pd.DataFrame, fit: dict, scoring: dict[str, float], n: int, rng: np.random.Generator
) -> np.ndarray:
    """Simulated league points, shape (len(rows), n)."""
    q = np.array(fit["pa_resid_quantiles"])
    u = rng.random((len(rows), n))
    pa = np.clip(rows["opp_implied"].to_numpy()[:, None] + np.interp(u, LEVELS, q), 0, None)
    pts = pa_points(pa, scoring)
    for c, k in DEF_COUNTS.items():
        pts += rng.poisson(_predict(fit["counts"][c], rows)[:, None], (len(rows), n)) * scoring.get(k, 0.0)
    return pts


def draw_kicker(
    rows: pd.DataFrame, fit: dict, scoring: dict[str, float], n: int, rng: np.random.Generator
) -> np.ndarray:
    pts = np.zeros((len(rows), n))
    for b in BANDS:
        att = rng.poisson(_predict(fit["attempts"][f"fga_{b}"], rows)[:, None], (len(rows), n))
        made = rng.binomial(att, fit["make_rate"][b])
        pts += made * scoring.get(f"fgm_{b}", 0.0) + (att - made) * scoring.get("fgmiss", 0.0)
    xpa = rng.poisson(_predict(fit["attempts"]["xpa"], rows)[:, None], (len(rows), n))
    xpm = rng.binomial(xpa, fit["make_rate"]["xp"])
    return pts + xpm * scoring.get("xpm", 0.0) + (xpa - xpm) * scoring.get("xpmiss", 0.0)
