from datetime import UTC, datetime

import pandas as pd
import pytest
import requests

from nfl_model import record
from nfl_model.props import TEAMS, event_teams, player_name, prop_rows, selection_team

AT = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "event, teams",
    [
        ("26OCT25LARLV", ("LAR", "LV")),  # LA + RLV is not two team codes
        ("26OCT25NYGHOU", ("NYG", "HOU")),
        ("26OCT25GBDET", ("GB", "DET")),
        ("26OCT25KCSEA", ("KC", "SEA")),
        ("26OCT25TBCAR", ("TB", "CAR")),
        ("not-an-event", None),
    ],
)
def test_event_teams(event, teams):
    assert event_teams(event) == teams


def test_every_two_code_pair_splits_one_way():
    for away in TEAMS:
        for home in TEAMS - {away}:
            assert event_teams(f"26OCT25{away}{home}") == (away, home)


def test_selection_team():
    assert selection_team("26OCT25LARLV", "LARJWHITTINGTON88") == "LAR"
    assert selection_team("26OCT25LARLV", "LVCHEYWARD34") == "LV"
    assert selection_team("26OCT25DENARI", "DENDENDST") == "DEN"
    assert selection_team("26OCT25KCSEA", "SEA25") == "SEA"


def market(series, event, selection, sub, strike=None, player=True, threshold=None):
    ticker = f"{series}-{event}-{selection}" + (f"-{threshold}" if threshold else "")
    return {
        "event_ticker": f"{series}-{event}",
        "ticker": ticker,
        "title": sub,
        "yes_sub_title": sub,
        "floor_strike": strike,
        "strike_type": "greater" if strike is not None else "structured",
        "custom_strike": {"football_player": "p-1", "football_team": "t-1"}
        if player
        else {"football_team": "t-1"},
        "yes_bid_dollars": "0.4400",
        "yes_ask_dollars": "0.4900",
        "last_price_dollars": "0.4500",
        "volume_fp": "120.00",
        "open_interest_fp": "100.00",
        "status": "active",
        "occurrence_datetime": "2026-10-25T20:25:00Z",
        "close_time": "2026-11-08T20:25:00Z",
    }


def test_player_name():
    assert player_name(market("KXNFLPASSYDS", "26OCT25SFATL", "SFBPURDY13", "Brock Purdy: 175+", 174.5)) == (
        "Brock Purdy"
    )
    assert (
        player_name(market("KXNFLFIRSTTD", "26OCT26DALPHI", "DALHLUEPKE30", "Hunter Luepke"))
        == "Hunter Luepke"
    )
    assert (
        player_name(
            market("KXNFLTEAMTOTAL", "26OCT25KCSEA", "SEA25", "Seattle over 24.5 points", player=False)
        )
        is None
    )


def test_prop_rows():
    rows = prop_rows(
        "KXNFLRECYDS",
        [market("KXNFLRECYDS", "26OCT25TBCAR", "CARJMETCHIE13", "John Metchie III: 40+", 39.5, threshold=40)],
        AT,
    )
    assert rows == [
        {
            "snapshot_at": AT,
            "series": "KXNFLRECYDS",
            "event": "26OCT25TBCAR",
            "ticker": "KXNFLRECYDS-26OCT25TBCAR-CARJMETCHIE13-40",
            "team": "CAR",
            "player": "John Metchie III",
            "kalshi_player_id": "p-1",
            "floor_strike": 39.5,
            "strike_type": "greater",
            "yes_bid": 0.44,
            "yes_ask": 0.49,
            "last_price": 0.45,
            "volume": 120.0,
            "open_interest": 100.0,
            "status": "active",
            "occurrence_at": datetime(2026, 10, 25, 20, 25, tzinfo=UTC),
            "close_at": datetime(2026, 11, 8, 20, 25, tzinfo=UTC),
            "title": "John Metchie III: 40+",
        }
    ]
    assert set(rows[0]) == {f.name for f in record.PROP_SCHEMA}


def test_prop_failure_still_records_game_lines(monkeypatch):
    appended, alerts = [], []
    monkeypatch.setattr(
        record.lines, "snapshot", lambda at: (pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [1]}))
    )
    monkeypatch.setattr(
        record.props, "snapshot", lambda at: (_ for _ in ()).throw(requests.ConnectionError("down"))
    )
    monkeypatch.setattr(record.bigquery, "Client", lambda project: None)
    monkeypatch.setattr(
        record, "_append", lambda client, table, df, schema: appended.append(table) or len(df)
    )
    monkeypatch.setattr(record.alerts, "send", alerts.append)
    assert record.main() == 1
    assert appended == ["kalshi_markets", "kalshi_game_lines"]
    assert len(alerts) == 1 and "player props" in alerts[0]


def test_game_line_failure_still_records_props(monkeypatch):
    appended = []
    monkeypatch.setattr(
        record.lines, "snapshot", lambda at: (_ for _ in ()).throw(KeyError("yes_bid_dollars"))
    )
    monkeypatch.setattr(record.props, "snapshot", lambda at: pd.DataFrame({"a": [1, 2]}))
    monkeypatch.setattr(record.bigquery, "Client", lambda project: None)
    monkeypatch.setattr(
        record, "_append", lambda client, table, df, schema: appended.append(table) or len(df)
    )
    monkeypatch.setattr(record.alerts, "send", lambda msg: None)
    assert record.main() == 1
    assert appended == ["kalshi_player_props"]
