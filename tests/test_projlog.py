from datetime import UTC, datetime

import pandas as pd

from nfl_model.projlog import SCHEMA, snapshot_rows

AT = datetime(2026, 10, 25, 15, tzinfo=UTC)
META = {
    "league_id": "L1",
    "dbt_target": "prod",
    "model_card_sha": "abc",
    "git_commit": "def",
    "scoring_sha": "123",
}


def _players() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sleeper_id": ["1", "2", None],
            "name": ["QB One", "Kicker", "No id"],
            "position": ["QB", "K", "WR"],
            "sleeper_team": ["GB", "TB", "SEA"],
            "team": ["GB", "TB", "SEA"],
            "proj": [17.66, 7.75, 3.0],
            "center": [18.3, 7.75, 3.0],
            "ours": [17.53, None, 2.0],
            "sleeper": [19.36, 7.75, 3.5],
            "kickoff_utc": [pd.Timestamp("2026-10-25 17:00", tz="UTC"), None, None],
            "q_play": [1.0, None, 1.0],
            "_i": [0, 1, 2],  # league-tool internals are not logged
        }
    )


def test_snapshot_rows_match_schema_and_carry_metadata():
    rows = snapshot_rows(_players(), AT, 2026, 7, META)
    assert list(rows.columns) == [f.name for f in SCHEMA]
    assert len(rows) == 2  # the row without a Sleeper ID is dropped
    assert rows["model_card_sha"].eq("abc").all() and rows["week"].eq(7).all()
    assert rows.loc[0, "proj"] == 17.66 and pd.isna(rows.loc[1, "ours"])


def test_snapshot_rows_fill_missing_columns_with_nulls():
    rows = snapshot_rows(_players(), AT, 2026, 7, META)
    # Columns the table lacks (no Questionable players this week, say) are logged as null
    assert rows["practice_status"].isna().all()
    assert rows["blend_matchup"].isna().all()
