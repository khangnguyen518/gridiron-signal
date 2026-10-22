"""Paired, week-clustered bootstrap for comparing two projections on the same rows.

Rows in the same week share game outcomes (a blowout or a weather game moves every player
in it), so whole weeks are resampled, not rows. Both models are scored on every resample,
which keeps the comparison paired: the interval is on the gap, not on each MAE alone.
"""

import numpy as np
import pandas as pd

N_BOOT = 2000
SEED = 20261021
WEEK = ["season", "week"]


def week_resamples(n_weeks: int, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    """How many times each week is drawn in each resample, shape (n_boot, n_weeks)."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_weeks, np.full(n_weeks, 1 / n_weeks), size=n_boot)


def _interval(estimate: float, boots: np.ndarray) -> dict[str, float]:
    """95% percentile interval, and a two-sided p-value: twice the share of resamples
    on the far side of zero."""
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p = min(1.0, 2 * min(np.mean(boots <= 0), np.mean(boots >= 0)))
    return {"estimate": float(estimate), "lo": float(lo), "hi": float(hi), "p": float(p)}


def mae_gap(df: pd.DataFrame, a: str, b: str, n_boot: int = N_BOOT, seed: int = SEED) -> dict[str, float]:
    """MAE of `a` minus MAE of `b` on the same rows. Negative means `a` is better."""
    y = df["fantasy_points"]
    weeks = df.assign(d=(df[a] - y).abs() - (df[b] - y).abs()).groupby(WEEK)["d"].agg(["sum", "count"])
    counts = week_resamples(len(weeks), n_boot, seed)
    boots = counts @ weeks["sum"].to_numpy() / (counts @ weeks["count"].to_numpy())
    estimate = weeks["sum"].sum() / weeks["count"].sum()
    return {**_interval(estimate, boots), "n": int(weeks["count"].sum()), "n_weeks": len(weeks)}


def close_call_gap(
    counts_a: pd.DataFrame, counts_b: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED
) -> dict[str, float]:
    """Close-call accuracy of `a` minus `b`, from per-week `wins` and `pairs` counts
    (`backtest.close_call_counts`). Positive means `a` is better."""
    weeks = (
        counts_a.groupby(WEEK)[["wins", "pairs"]]
        .sum()
        .join(counts_b.groupby(WEEK)[["wins", "pairs"]].sum(), lsuffix="_a", rsuffix="_b", how="outer")
        .fillna(0)
    )
    counts = week_resamples(len(weeks), n_boot, seed)
    acc_a = counts @ weeks["wins_a"].to_numpy() / (counts @ weeks["pairs_a"].to_numpy())
    acc_b = counts @ weeks["wins_b"].to_numpy() / (counts @ weeks["pairs_b"].to_numpy())
    estimate = weeks["wins_a"].sum() / weeks["pairs_a"].sum() - weeks["wins_b"].sum() / weeks["pairs_b"].sum()
    return {**_interval(estimate, acc_a - acc_b), "n": int(weeks["pairs_a"].sum()), "n_weeks": len(weeks)}
