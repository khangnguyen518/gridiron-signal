from datetime import UTC, date, datetime

import pandas as pd
import pytest

from nfl_model.lines import event_date, game_lines, ladder_median, market_rows


def test_ladder_median_interpolates():
    assert ladder_median([(40.5, 0.7), (43.5, 0.55), (46.5, 0.4)]) == pytest.approx(43.5 + 0.05 / 0.15 * 3)


def test_ladder_median_none_when_no_crossing():
    assert ladder_median([(40.5, 0.9), (43.5, 0.8)]) is None


def market(series, ticker, bid, ask, strike=None):
    return {
        "event_ticker": f"{series}-26OCT26DALPHI",
        "ticker": f"{series}-26OCT26DALPHI-{ticker}",
        "yes_bid_dollars": str(bid),
        "yes_ask_dollars": str(ask),
        "floor_strike": strike,
        "occurrence_datetime": "2026-10-27T03:15:00Z",
        "status": "active",
    }


def snapshot_frame():
    at = datetime(2026, 10, 25, 12, tzinfo=UTC)
    rows = market_rows(
        "KXNFLSPREAD",
        [
            market("KXNFLSPREAD", "PHI3", 0.56, 0.58, 2.5),  # P(PHI by > 2.5) = 0.57
            market("KXNFLSPREAD", "PHI4", 0.46, 0.48, 3.5),  # P(PHI by > 3.5) = 0.47
            market("KXNFLSPREAD", "DAL3", 0.30, 0.32, 2.5),  # P(DAL by > 2.5) = 0.31
        ],
        at,
    )
    rows += market_rows(
        "KXNFLTOTAL",
        [
            market("KXNFLTOTAL", "44", 0.54, 0.56, 43.5),
            market("KXNFLTOTAL", "47", 0.44, 0.46, 46.5),
            market("KXNFLTOTAL", "50", 0.0, 0.05, 49.5),  # no bid: skipped
        ],
        at,
    )
    rows += market_rows(
        "KXNFLGAME",
        [
            market("KXNFLGAME", "PHI", 0.64, 0.66),
            market("KXNFLGAME", "DAL", 0.36, 0.38),
        ],
        at,
    )
    return pd.DataFrame(rows)


def test_event_date_parses_kalshi_tickers():
    assert event_date("26OCT26DALPHI") == date(2026, 10, 26)
    assert event_date("not-an-event") is None


def test_market_rows_keep_team_codes():
    df = snapshot_frame()
    assert set(df.loc[df["series"] == "KXNFLSPREAD", "team"]) == {"PHI", "DAL"}
    assert df.loc[df["series"] == "KXNFLTOTAL", "team"].isna().all()


def test_game_lines_from_ladders():
    g = game_lines(snapshot_frame()).iloc[0]
    assert (g["away"], g["home"]) == ("DAL", "PHI")
    # home ladder crosses 0.5 at 2.5 + 0.07 / 0.10 = 3.2 (the DAL market sits at -2.5, below it)
    assert g["home_spread"] == pytest.approx(3.2)
    assert g["total"] == pytest.approx(43.5 + 0.05 / 0.10 * 3)
    assert g["home_win_prob"] == pytest.approx(0.65 / (0.65 + 0.37))
    assert g["total_markets"] == 2
