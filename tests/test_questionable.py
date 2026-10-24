import pandas as pd

from nfl_model.backtest import questionable_pair_counts
from nfl_model.questionable import factors, fit, previous_played


def test_previous_played_is_per_team_and_ordered():
    status = pd.DataFrame(
        {
            "gsis_id": ["a", "a", "a", "a"],
            "team": ["X", "X", "X", "Y"],
            "kickoff_utc": pd.to_datetime(["2020-09-20", "2020-09-13", "2020-09-27", "2020-10-04"]),
            "played": [False, True, True, True],
        }
    )
    # by kickoff: 13th played, 20th sat, 27th played; the first game on Y has no previous game
    assert previous_played(status).tolist() == [True, False, False, False]


def _rows(practice: str, played: list[int], actual: list[float], projected: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "injury_status": "Questionable",
            "practice_status": practice,
            "regular": True,
            "played": played,
            "fantasy_points": actual,
            "opp_points": projected,
        }
    )


def test_fit_play_rate_and_multiplier_relative_to_healthy():
    healthy = pd.DataFrame(
        {
            "injury_status": [None] * 40,
            "practice_status": None,
            "regular": True,
            "played": 1,
            "fantasy_points": 11.0,
            "opp_points": 10.0,
        }
    )
    # 40 DNP rows: half played, scoring 8.8 against 10 projected -> 0.88 / 1.10 healthy = 0.8
    dnp = _rows("DNP", [1, 0] * 20, [8.8, 0.0] * 20)
    table = fit(pd.concat([healthy, dnp], ignore_index=True))
    assert table["DNP"]["play"] == 0.5
    assert table["DNP"]["mult"] == 0.8
    # Too few Limited or Full rows: they fall back to the pooled Questionable rate
    assert table["Limited"] == table["all"] == table["DNP"] | {"n": 40}


def test_factors_only_touch_questionable_players():
    table = {k: {"play": 0.5, "mult": 0.8, "n": 40} for k in ["all", "DNP", "Limited", "Full"]}
    table["Full"] = {"play": 0.9, "mult": 1.0, "n": 40}
    df = pd.DataFrame(
        {
            "injury_status": [None, "Questionable", "Questionable", "Doubtful"],
            "practice_status": [None, "Full", None, "DNP"],
        }
    )
    play, mult = factors(df, table)
    assert play.tolist() == [1.0, 0.9, 0.5, 1.0]
    assert mult.tolist() == [1.0, 1.0, 0.8, 1.0]


def test_questionable_pairs():
    df = pd.DataFrame(
        {
            "season": 2020,
            "week": 1,
            "position": "WR",
            "injury_status": ["Questionable", None, None],
            "base": [10.0, 9.5, 15.0],
            "adj": [6.0, 9.5, 15.0],
            "fantasy_points": [0.0, 8.0, 20.0],
        }
    )
    # Only the Questionable WR vs the 9.5 WR is a close pair; the adjustment flips it correctly
    assert questionable_pair_counts(df, "base", "adj")[["wins", "pairs"]].iloc[0].tolist() == [1, 1]
    assert questionable_pair_counts(df, "base", "base")[["wins", "pairs"]].iloc[0].tolist() == [0, 1]
