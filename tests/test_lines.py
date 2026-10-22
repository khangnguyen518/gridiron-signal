import pytest

from nfl_model.lines import ladder_median


def test_ladder_median_interpolates():
    assert ladder_median([(40.5, 0.7), (43.5, 0.55), (46.5, 0.4)]) == pytest.approx(43.5 + 0.05 / 0.15 * 3)


def test_ladder_median_none_when_no_crossing():
    assert ladder_median([(40.5, 0.9), (43.5, 0.8)]) is None


def test_spread_from_both_team_ladders():
    # home favored by ~3: P(home margin > 2.5) = 0.55, away ladder P(away margin > -? ) expressed as home
    home = [(2.5, 0.55), (3.5, 0.45)]
    away = [(-x, 1 - p) for x, p in [(-3.5, 0.55)]]  # away "wins by over -3.5" is home margin < 3.5
    assert ladder_median(home + away) == pytest.approx(3.0)
