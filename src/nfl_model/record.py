"""Record Kalshi NFL lines: append one snapshot of every open market and the game
lines derived from it to BigQuery. Run hourly on the VM (deploy/crontab).

    uv run nflm record-lines

Tables in NFLM_RAW_DATASET (default nflm_raw), append-only, partitioned by
DATE(snapshot_at), clustered by event:
    kalshi_markets     one row per market per snapshot: bid, ask, last, volume, open interest
    kalshi_game_lines  one row per game per snapshot: median spread and total, win probability
    kalshi_player_props  one row per player-prop market per snapshot (decision 0015)

Raw tables are shared by every environment, like sports_db's: laptops and the VM append to
the same tables, and dbt reads them in both targets. Never update or delete rows.
"""

import sys
from datetime import UTC, datetime

import requests
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery

from nfl_model import alerts, config, lines, props

MARKET_SCHEMA = [
    bigquery.SchemaField("snapshot_at", "TIMESTAMP", "REQUIRED"),
    bigquery.SchemaField("series", "STRING", "REQUIRED"),
    bigquery.SchemaField("event", "STRING", "REQUIRED"),
    bigquery.SchemaField("ticker", "STRING", "REQUIRED"),
    bigquery.SchemaField("team", "STRING"),
    bigquery.SchemaField("floor_strike", "FLOAT"),
    bigquery.SchemaField("yes_bid", "FLOAT"),
    bigquery.SchemaField("yes_ask", "FLOAT"),
    bigquery.SchemaField("last_price", "FLOAT"),
    bigquery.SchemaField("volume", "FLOAT"),
    bigquery.SchemaField("open_interest", "FLOAT"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("occurrence_at", "TIMESTAMP"),
    bigquery.SchemaField("close_at", "TIMESTAMP"),
]
GAME_SCHEMA = [
    bigquery.SchemaField("snapshot_at", "TIMESTAMP", "REQUIRED"),
    bigquery.SchemaField("event", "STRING", "REQUIRED"),
    bigquery.SchemaField("event_date", "DATE"),
    bigquery.SchemaField("away", "STRING"),
    bigquery.SchemaField("home", "STRING"),
    bigquery.SchemaField("home_spread", "FLOAT"),
    bigquery.SchemaField("total", "FLOAT"),
    bigquery.SchemaField("home_win_prob", "FLOAT"),
    bigquery.SchemaField("spread_markets", "INTEGER"),
    bigquery.SchemaField("total_markets", "INTEGER"),
    bigquery.SchemaField("game_end_at", "TIMESTAMP"),
]
PROP_SCHEMA = [
    bigquery.SchemaField("snapshot_at", "TIMESTAMP", "REQUIRED"),
    bigquery.SchemaField("series", "STRING", "REQUIRED"),
    bigquery.SchemaField("event", "STRING", "REQUIRED"),
    bigquery.SchemaField("ticker", "STRING", "REQUIRED"),
    bigquery.SchemaField("team", "STRING"),
    bigquery.SchemaField("player", "STRING"),
    bigquery.SchemaField("kalshi_player_id", "STRING"),
    bigquery.SchemaField("floor_strike", "FLOAT"),
    bigquery.SchemaField("strike_type", "STRING"),
    bigquery.SchemaField("yes_bid", "FLOAT"),
    bigquery.SchemaField("yes_ask", "FLOAT"),
    bigquery.SchemaField("last_price", "FLOAT"),
    bigquery.SchemaField("volume", "FLOAT"),
    bigquery.SchemaField("open_interest", "FLOAT"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("occurrence_at", "TIMESTAMP"),
    bigquery.SchemaField("close_at", "TIMESTAMP"),
    bigquery.SchemaField("title", "STRING"),
]
# Kalshi down, a changed field, or BigQuery refusing the load
ERRORS = (requests.RequestException, GoogleAPIError, KeyError, ValueError)


def _append(
    client: bigquery.Client,
    table: str,
    df,
    schema: list[bigquery.SchemaField],
    clustering: list[str] | None = None,
) -> int:
    if df.empty:
        return 0
    job = client.load_table_from_dataframe(
        df[[f.name for f in schema]],
        f"{config.NFLM_GCP_PROJECT}.{config.NFLM_RAW_DATASET}.{table}",
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            time_partitioning=bigquery.TimePartitioning(field="snapshot_at"),
            clustering_fields=clustering or ["event"],
        ),
    )
    job.result()
    return len(df)


def main() -> int:
    at = datetime.now(UTC)
    ok = True
    try:
        markets, games = lines.snapshot(at)
        client = bigquery.Client(project=config.NFLM_GCP_PROJECT)
        n_markets = _append(client, "kalshi_markets", markets, MARKET_SCHEMA)
        n_games = _append(client, "kalshi_game_lines", games, GAME_SCHEMA)
        print(f"{at:%Y-%m-%d %H:%M} UTC: recorded {n_markets} markets, {n_games} games")
    except ERRORS as exc:
        alerts.send(f"gridiron-signal record-lines failed at {at:%Y-%m-%d %H:%M} UTC: {exc!r}")
        ok = False
    # Separate, so a problem with props never costs an hour of game lines
    try:
        client = bigquery.Client(project=config.NFLM_GCP_PROJECT)
        n_props = _append(client, "kalshi_player_props", props.snapshot(at), PROP_SCHEMA)
        print(f"{at:%Y-%m-%d %H:%M} UTC: recorded {n_props} player prop markets")
    except ERRORS as exc:
        alerts.send(f"gridiron-signal record-lines (player props) failed at {at:%Y-%m-%d %H:%M} UTC: {exc!r}")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
