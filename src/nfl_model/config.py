"""Settings read from the environment (.env). Every module reads config from here."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

NFLM_GCP_PROJECT = os.getenv("NFLM_GCP_PROJECT", "gen-lang-client-0525946386")
NFLM_DATASET = os.getenv("NFLM_DATASET", "nflm_dev")
NFLM_DBT_TARGET = os.getenv("NFLM_DBT_TARGET", "dev")
# Append-only raw data this repo records itself (Kalshi lines), shared by every environment
NFLM_RAW_DATASET = os.getenv("NFLM_RAW_DATASET", "nflm_raw")
SPORTS_DB_PROJECT = os.getenv("SPORTS_DB_PROJECT", "sports-db-209650")
SPORTS_DB_STAGING = os.getenv("SPORTS_DB_STAGING", "dev_staging")
SLEEPER_LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID") or None
SLEEPER_USERNAME = os.getenv("SLEEPER_USERNAME") or None
# Discord alerts: a webhook URL directly, or a Secret Manager secret version that holds it
NFLM_ALERT_WEBHOOK_URL = os.getenv("NFLM_ALERT_WEBHOOK_URL") or None
NFLM_ALERT_SECRET = os.getenv("NFLM_ALERT_SECRET") or None

CACHE_DIR = ROOT / "data" / "cache"
OUTPUT_DIR = ROOT / "output"
# The live model: written by `nflm backtest`, committed to deploy it
MODEL_CARD = ROOT / "model" / "model_card.json"

POSITIONS = ["QB", "RB", "WR", "TE"]
