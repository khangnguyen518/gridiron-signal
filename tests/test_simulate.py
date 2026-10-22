import numpy as np
import pandas as pd
import pytest

from nfl_model.league import max_win_lineup, win_probability
from nfl_model.simulate import SimParams, quantile_frame, rescale, simulate


def team_rows(team: str, is_home: bool, game: str = "g1") -> list[dict]:
    base = {
        "game_id": game,
        "team": team,
        "is_home": is_home,
        "implied_points": 24.0,
        "spread": 0.0,
        "total_line": 48.0,
        "team_pass_attempts_hat": 35.0,
        "team_rush_attempts_hat": 25.0,
        "team_pass_tds_hat": 1.6,
        "team_rush_tds_hat": 0.9,
        "int_rate": 0.02,
        "prior_fumble_rate": 0.005,
        "catch_rate": 0.65,
        "yds_per_target": 8.0,
        "yds_per_carry": 4.3,
    }
    return [
        {
            **base,
            "position": "QB",
            "att_share": 1.0,
            "target_share": 0.0,
            "carry_share": 0.1,
            "rz_target_share": 0.0,
            "rz_carry_share": 0.1,
        },
        {
            **base,
            "position": "WR",
            "att_share": 0.0,
            "target_share": 0.28,
            "carry_share": 0.0,
            "rz_target_share": 0.3,
            "rz_carry_share": 0.0,
        },
        {
            **base,
            "position": "RB",
            "att_share": 0.0,
            "target_share": 0.1,
            "carry_share": 0.7,
            "rz_target_share": 0.1,
            "rz_carry_share": 0.7,
        },
    ]


def game() -> pd.DataFrame:
    return pd.DataFrame(team_rows("AAA", True) + team_rows("BBB", False))


def test_simulate_shape_and_sensible_means():
    draws = simulate(game(), SimParams(), n=4000, seed=1)
    assert draws.shape == (6, 4000)
    means = draws.mean(axis=1)
    assert 12 < means[0] < 28  # QB
    assert 8 < means[1] < 22  # WR1 with 28% of targets
    assert means[2] > 8  # RB with 70% of carries


def test_qb_and_his_receiver_move_together():
    draws = simulate(game(), SimParams(), n=4000, seed=2)
    assert np.corrcoef(draws[0], draws[1])[0, 1] > 0.15  # QB and own WR
    assert abs(np.corrcoef(draws[1], draws[4])[0, 1]) < 0.15  # WRs on opposite teams


def test_same_seed_same_draws():
    np.testing.assert_array_equal(
        simulate(game(), SimParams(), n=50, seed=3), simulate(game(), SimParams(), n=50, seed=3)
    )


def test_rescale_and_quantiles():
    draws = np.array([[1.0, 2.0, 3.0, 4.0], [0.0, 0.0, 0.0, 0.0]])
    out = rescale(draws, np.array([5.0, 3.0]))
    assert out[0].mean() == pytest.approx(5.0)
    assert (out[1] == 0).all()  # nothing to scale
    assert list(quantile_frame(out).columns) == ["p10", "p25", "p50", "p75", "p90"]


def test_win_probability_counts_ties_as_half():
    draws = np.array([[10.0, 10.0, 0.0, 30.0], [10.0, 5.0, 5.0, 10.0]])
    assert win_probability([0], [1], draws) == pytest.approx((0.5 + 1 + 0 + 1) / 4)


def test_underdog_prefers_the_boom_player():
    rng = np.random.default_rng(0)
    n = 5000
    draws = np.vstack(
        [
            np.full(n, 10.0),  # 0: steady starter, 10 every week
            rng.normal(9.5, 8.0, n),  # 1: boom-or-bust bench player, slightly lower mean
            rng.normal(25.0, 2.0, n),  # 2: opponent, heavy favorite
        ]
    )
    players = pd.DataFrame(
        {
            "name": ["steady", "boom", "opp"],
            "position": ["WR", "WR", "WR"],
            "proj": [10.0, 9.5, 25.0],
            "_i": [0, 1, 2],
        }
    )
    lineup = players.iloc[[0]].assign(slot="WR")
    bench = players.iloc[[1]]
    best, swaps, win = max_win_lineup(lineup, bench, [2], draws, players)
    assert list(best["name"]) == ["boom"]
    assert swaps == [("WR", "boom", "steady")]
    assert win > win_probability([0], [2], draws)
