import numpy as np
import pandas as pd

from nfl_model.backtest import close_call_accuracy, close_call_counts
from nfl_model.significance import close_call_gap, mae_gap, week_resamples


def _frame(err_a: list[list[float]], err_b: list[list[float]]) -> pd.DataFrame:
    """One row per player: actual 10, projections off by the given errors, one list per week."""
    rows = []
    for week, (wa, wb) in enumerate(zip(err_a, err_b), start=1):
        for ea, eb in zip(wa, wb):
            rows.append(
                {"season": 2020, "week": week, "fantasy_points": 10.0, "a": 10.0 + ea, "b": 10.0 + eb}
            )
    return pd.DataFrame(rows)


def test_week_resamples_draw_every_week_count():
    counts = week_resamples(17, n_boot=50)
    assert counts.shape == (50, 17)
    assert (counts.sum(axis=1) == 17).all()


def test_identical_models_have_zero_gap():
    df = _frame([[1.0, -2.0]] * 5, [[1.0, -2.0]] * 5)
    out = mae_gap(df, "a", "b", n_boot=200)
    assert out["estimate"] == out["lo"] == out["hi"] == 0.0
    assert out["p"] == 1.0


def test_consistently_better_model_is_significant():
    df = _frame([[1.0, 1.0]] * 20, [[2.0, -2.0]] * 20)
    out = mae_gap(df, "a", "b", n_boot=500)
    assert out["estimate"] == -1.0
    assert out["hi"] < 0
    assert out["p"] < 0.01


def test_week_shocks_widen_the_interval():
    # 6 weeks favor a by 1 point and 4 favor b by 1, with 100 players each: row by row the
    # gap looks certain, but there are only 10 independent weeks
    err_a = [[0.0] * 100] * 6 + [[2.0] * 100] * 4
    err_b = [[1.0] * 100] * 10
    out = mae_gap(_frame(err_a, err_b), "a", "b", n_boot=2000)
    assert np.isclose(out["estimate"], -0.2)
    assert out["lo"] < 0 < out["hi"]
    assert out["n_weeks"] == 10


def test_close_call_counts_match_accuracy():
    df = pd.DataFrame(
        {
            "season": 2020,
            "week": [1, 1, 1, 2, 2],
            "position": "WR",
            "sleeper_projected_points": [10.0, 11.0, 30.0, 8.0, 9.0],
            "fantasy_points": [5.0, 12.0, 20.0, 9.0, 3.0],
            "proj": [9.0, 12.0, 30.0, 8.0, 7.0],
        }
    )
    counts = close_call_counts(df, "proj")
    # week 1: only the 10 vs 11 pair is close, ordered right; week 2: one pair, ordered right
    assert counts[["wins", "pairs"]].sum().tolist() == [2, 2]
    assert close_call_accuracy(df, "proj") == (1.0, 2)


def test_close_call_gap_from_counts():
    a = pd.DataFrame({"season": 2020, "week": [1, 2], "position": "WR", "wins": [6, 6], "pairs": [10, 10]})
    b = a.assign(wins=[5, 5])
    out = close_call_gap(a, b, n_boot=200)
    assert np.isclose(out["estimate"], 0.1)
    assert out["n"] == 20
