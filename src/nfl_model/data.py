"""Loads the dbt tables from BigQuery, cached as Parquet so backtests rerun for free."""

from pathlib import Path

import pandas as pd
from google.cloud import bigquery

from nfl_model import config


def _table(name: str) -> str:
    return f"`{config.NFLM_GCP_PROJECT}.{config.NFLM_DATASET}.{name}`"


def _cached_query(name: str, sql: str, refresh: bool) -> pd.DataFrame:
    path: Path = config.CACHE_DIR / f"{name}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    df = bigquery.Client(project=config.NFLM_GCP_PROJECT).query(sql).to_dataframe()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def load_player_games(refresh: bool = False) -> pd.DataFrame:
    df = _cached_query("player_games", f"select * from {_table('fct_player_game_inputs')}", refresh)
    return df.sort_values(["gsis_id", "kickoff_utc"]).reset_index(drop=True)


def load_team_games(refresh: bool = False) -> pd.DataFrame:
    """Team games with each team's play-calling and red-zone numbers (null before kickoff)."""
    sql = f"""
        select tg.*, s.* except (game_id, team)
        from {_table("int_team_games")} as tg
        left join {_table("int_team_game_situations")} as s using (game_id, team)
    """
    df = _cached_query("team_games", sql, refresh)
    return df.sort_values(["team", "kickoff_utc"]).reset_index(drop=True)


def load_xwalk(refresh: bool = False) -> pd.DataFrame:
    return _cached_query("xwalk", f"select * from {_table('int_player_xwalk')}", refresh)


def load_player_status(refresh: bool = False) -> pd.DataFrame:
    return _cached_query("player_status", f"select * from {_table('int_player_game_status')}", refresh)
