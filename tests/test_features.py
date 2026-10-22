import numpy as np
import pandas as pd
import pytest

from nfl_model.features import lagged_wsum


def test_lagged_wsum_uses_only_earlier_rows():
    groups = pd.Series(["a", "a", "a", "b", "b"])
    values = pd.Series([1.0, 2.0, 4.0, 10.0, 20.0])
    out = lagged_wsum(values, groups, half_life=1.0)
    # half-life 1: previous game weight 1, the one before 0.5
    np.testing.assert_allclose(out, [0.0, 1.0, 2.0 + 0.5 * 1.0, 0.0, 10.0])


def test_lagged_wsum_ignores_current_game():
    groups = pd.Series(["a"] * 4)
    base = lagged_wsum(pd.Series([3.0, 5.0, 7.0, 9.0]), groups, half_life=2.0)
    changed = lagged_wsum(pd.Series([3.0, 5.0, 7.0, 900.0]), groups, half_life=2.0)
    # equal up to float roundoff: the current game's value is subtracted back out
    assert abs(base.iloc[3] - changed.iloc[3]) < 1e-9


def test_lagged_wsum_long_history_is_stable():
    n = 300
    groups = pd.Series(["a"] * n)
    out = lagged_wsum(pd.Series(np.ones(n)), groups, half_life=1.0)
    # geometric series 1 + 0.5 + 0.25 + ... -> 2
    assert abs(out.iloc[-1] - 2.0) < 1e-9


def test_placeholder_rows_do_not_age_history():
    groups = pd.Series(["a"] * 4)
    values = pd.Series([2.0, 0.0, 4.0, 0.0])
    step = pd.Series([1, 0, 1, 1])
    out = lagged_wsum(values, groups, half_life=1.0, step=step)
    # row 1 is a placeholder: sees game 0 at full weight; row 2 sees game 0 still at weight 1;
    # row 3 sees game 2 at 1 and game 0 at 0.5
    np.testing.assert_allclose(out, [0.0, 2.0, 2.0, 4.0 + 0.5 * 2.0])


def test_default_step_matches_all_games():
    groups = pd.Series(["a", "a", "b", "a"])
    values = pd.Series([1.0, 3.0, 5.0, 7.0])
    np.testing.assert_allclose(
        lagged_wsum(values, groups, 2.0), lagged_wsum(values, groups, 2.0, pd.Series([1, 1, 1, 1]))
    )


def test_team_features_use_earlier_games_and_merge_opponent_defense():
    from nfl_model.features import add_team_features

    ko = pd.to_datetime(["2025-09-07", "2025-09-14", "2025-09-21"] * 2)
    base = {
        "pass_attempts": 30.0,
        "rush_attempts": 25.0,
        "pass_tds": 1.0,
        "rush_tds": 1.0,
        "points_scored": 20.0,
        "off_plays": 60.0,
        "off_pass_plays": 32.0,
        "off_neutral_plays": 30.0,
        "off_rz_plays": 8.0,
        "off_rz_pass_plays": 4.0,
        "off_rz_trips": 3.0,
        "off_rz_trip_tds": 2.0,
        "off_rz_pass_tds": 1.0,
        "off_rz_rush_tds": 1.0,
        "def_plays": 60.0,
        "def_neutral_plays": 30.0,
        "def_neutral_pass_plays": 15.0,
        "def_rz_trips": 3.0,
        "def_rz_trip_tds": 1.0,
        "def_rz_pass_tds": 1.0,
        "def_rz_rush_tds": 0.0,
    }
    rows = []
    for i, (team, opp) in enumerate([("AAA", "BBB")] * 3 + [("BBB", "AAA")] * 3):
        rows.append(
            {
                **base,
                "game_id": f"g{i % 3}",
                "team": team,
                "opponent": opp,
                "kickoff_utc": ko[i],
                "head_coach": "Coach A" if team == "AAA" else "Coach B",
                "off_neutral_pass_plays": [10.0, 20.0, 30.0][i % 3] if team == "AAA" else 15.0,
            }
        )
    out = add_team_features(pd.DataFrame(rows), hl_team=1e9, coach_k=None).set_index(["team", "game_id"])
    assert out.loc[("AAA", "g0"), "team_neutral_pass_rate"] == pytest.approx(0.53)  # no history: league
    assert out.loc[("AAA", "g2"), "team_neutral_pass_rate"] == pytest.approx(30 / 60)  # games 0 and 1 only
    assert out.loc[("AAA", "g1"), "opp_def_rz_td_rate"] == pytest.approx(1 / 3)  # BBB's defense before g1
