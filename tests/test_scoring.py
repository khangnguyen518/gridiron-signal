import pandas as pd
import pytest

from nfl_model.scoring import fantasy_points


def test_default_scoring_full_ppr():
    row = pd.DataFrame(
        [
            {
                "position": "WR",
                "receptions": 5,
                "rec_yards": 80,
                "rec_tds": 1,
                "rush_yards": 10,
                "fumbles_lost": 1,
            }
        ]
    )
    assert fantasy_points(row).iloc[0] == pytest.approx(5 + 8 + 6 + 1 - 2)


def test_qb_line():
    row = pd.DataFrame([{"position": "QB", "pass_yards": 250, "pass_tds": 2, "interceptions": 1}])
    assert fantasy_points(row).iloc[0] == pytest.approx(10 + 8 - 1)


def test_te_premium_only_for_tes():
    rows = pd.DataFrame([{"position": "TE", "receptions": 4}, {"position": "WR", "receptions": 4}])
    pts = fantasy_points(rows, {"rec": 1.0, "bonus_rec_te": 0.5})
    assert list(pts) == [6.0, 4.0]
