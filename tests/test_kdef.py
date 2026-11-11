import numpy as np
import pandas as pd

from nfl_model import kdef
from nfl_model.league import add_kdef
from nfl_model.scoring import DEFAULT_SCORING


def test_points_allowed_brackets_match_sleeper():
    pts = np.array([0, 1, 6, 7, 13, 14, 20, 21, 27, 28, 34, 35, 50])
    assert kdef.pa_points(pts, DEFAULT_SCORING).tolist() == [10, 7, 7, 4, 4, 1, 1, 0, 0, -1, -1, -4, -4]


def _defense(sacks: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(sacks)
    games = [f"g{i}" for i in range(n)]
    kick = pd.date_range("2024-09-08", periods=n, freq="7D", tz="UTC")
    tg = pd.DataFrame(
        {
            "game_id": games,
            "team": "AAA",
            "opponent": "BBB",
            "season": 2024,
            "week": range(1, n + 1),
            "kickoff_utc": kick,
            "spread": 3.0,
            "total_line": 44.0,
            "implied_points": 23.5,
            "points_scored": 20,
        }
    )
    dg = pd.DataFrame(
        {
            "game_id": games,
            "team": "AAA",
            "pts_allowed": 20,
            "sacks": sacks,
            **{c: 0.0 for c in kdef.DEF_COUNTS if c != "sacks"},
        }
    )
    return dg, tg


def test_defense_rates_use_only_earlier_games():
    dg, tg = _defense([1.0, 2.0, 3.0, 9.0])
    changed = dg.assign(sacks=[1.0, 2.0, 3.0, 40.0])
    a = kdef.defense_rows(dg, tg).set_index("game_id")
    b = kdef.defense_rows(changed, tg).set_index("game_id")
    assert np.isclose(a.loc["g3", "rate_sacks"], b.loc["g3", "rate_sacks"])  # its own game never counts
    assert a.loc["g3", "rate_sacks"] > a.loc["g1", "rate_sacks"]  # earlier games do


def test_upcoming_defense_row_gets_history():
    dg, tg = _defense([2.0, 4.0])
    up = tg.iloc[[0]].assign(game_id="g9", week=9, kickoff_utc=tg["kickoff_utc"].max() + pd.Timedelta(days=7))
    rows = kdef.defense_rows(dg, tg, upcoming=up)
    future = rows[rows["played"].eq(0)].iloc[0]
    assert future["opp_implied"] == 44.0 - 23.5
    assert future["rate_sacks"] > 0


def test_stretch_keeps_median_and_scales_spread():
    d = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
    s = kdef.stretch(d, 2.0)
    assert np.median(s) == 3.0 and s.max() - s.min() == 8.0


def test_calibrate_stretch_widens_too_narrow_draws():
    rng = np.random.default_rng(0)
    actual = rng.normal(0, 2, 4000)
    draws = rng.normal(0, 1, (4000, 400))  # half the true spread
    assert 1.8 <= kdef.calibrate_stretch(draws, actual) <= 2.2


def test_kicker_slot_goes_to_the_teams_top_kicker():
    df = pd.DataFrame(
        {
            "sleeper_id": ["k1", "k2", "GB", "k3"],
            "position": ["K", "K", "DEF", "K"],
            "team": ["GB", "GB", "GB", None],
            "sleeper": [8.0, 0.5, 6.0, 7.0],
            "ours": np.nan,
            "blend_w": np.nan,
            "blend_shift": np.nan,
            "blend_matchup": np.nan,
            "opponent": None,
        }
    )
    rows = {
        "K": pd.DataFrame({"team": ["GB"], "ours": [9.0], "opponent": ["DET"]}),
        "DEF": pd.DataFrame({"team": ["GB"], "ours": [7.5], "opponent": ["DET"]}),
    }
    fits = {"blend": {"K": {"w": 0.9, "shift": -0.5}, "DEF": {"w": 0.8, "shift": -0.7}}}
    out = add_kdef(df, rows, fits).set_index("sleeper_id")
    assert out.loc["k1", "ours"] == 9.0 and pd.isna(out.loc["k2", "ours"]) and pd.isna(out.loc["k3", "ours"])
    assert (
        out.loc["GB", "ours"] == 7.5
        and out.loc["GB", "blend_w"] == 0.8
        and out.loc["GB", "opponent"] == "DET"
    )
