import pandas as pd

from nfl_model.league import close_calls, optimal_lineup


def roster():
    return pd.DataFrame(
        [
            {"sleeper_id": "1", "name": "QB1", "position": "QB", "proj": 20.0},
            {"sleeper_id": "2", "name": "RB1", "position": "RB", "proj": 15.0},
            {"sleeper_id": "3", "name": "RB2", "position": "RB", "proj": 12.0},
            {"sleeper_id": "4", "name": "WR1", "position": "WR", "proj": 14.0},
            {"sleeper_id": "5", "name": "TE1", "position": "TE", "proj": 9.0},
            {"sleeper_id": "6", "name": "QB2", "position": "QB", "proj": 16.0},
        ]
    )


def test_flex_takes_best_leftover():
    lineup = optimal_lineup(roster(), ["QB", "RB", "WR", "TE", "FLEX"])
    assert dict(zip(lineup["slot"], lineup["name"])) == {
        "QB": "QB1",
        "RB": "RB1",
        "WR": "WR1",
        "TE": "TE1",
        "FLEX": "RB2",
    }


def test_superflex_can_start_second_qb():
    lineup = optimal_lineup(roster(), ["QB", "RB", "SUPER_FLEX"])
    assert set(lineup["name"]) == {"QB1", "RB1", "QB2"}


def test_close_calls_respect_slot_eligibility():
    r = roster()
    lineup = optimal_lineup(r, ["QB", "RB", "FLEX"])
    bench = r[~r["sleeper_id"].isin(lineup["sleeper_id"])]
    calls = close_calls(lineup, bench)
    # QB2 (16) is within 2 of nothing it can play; TE1 (9) is not within 2 of the flex RB2 (12)
    assert calls.empty or "QB2" not in set(calls["bench"])


def test_close_calls_report_win_probability_both_ways():
    import numpy as np

    r = roster().assign(_i=range(6))
    draws = np.vstack([np.full(100, float(p)) for p in r["proj"]] + [np.full(100, 60.0)])
    lineup = optimal_lineup(r, ["QB", "RB", "FLEX"])
    bench = r[~r["sleeper_id"].isin(lineup["sleeper_id"])]
    calls = close_calls(lineup, bench, [6], draws)
    assert {"win_as_is", "win_if_swapped"} <= set(calls.columns)


def test_lineup_ranks_on_the_unshifted_center():
    import pandas as pd

    from nfl_model.league import optimal_lineup

    # The WR's shifted projection is lower, but his unshifted center is higher: he takes the FLEX
    roster = pd.DataFrame(
        [
            {"sleeper_id": "1", "name": "WR1", "position": "WR", "proj": 10.0, "center": 10.8},
            {"sleeper_id": "2", "name": "WR2", "position": "WR", "proj": 9.2, "center": 10.04},
            {"sleeper_id": "3", "name": "TE1", "position": "TE", "proj": 11.0, "center": 11.46},
            {"sleeper_id": "4", "name": "TE2", "position": "TE", "proj": 9.5, "center": 9.96},
        ]
    )
    lineup = optimal_lineup(roster, ["WR", "TE", "FLEX"])
    assert lineup.set_index("slot")["name"]["FLEX"] == "WR2"
