"""Sleeper public API (no auth). Endpoints match fantasy-football-draft-helper's
sleeper_client.py; /v1/players/nfl is cached for a day, as Sleeper asks."""

import json
import time

import pandas as pd
import requests

from nfl_model import config

BASE = "https://api.sleeper.app"
_SESSION = requests.Session()

# Sleeper team code -> nflverse team code, where they differ
TEAM_TO_NFLVERSE = {"LAR": "LA"}


def _get(path: str, params: dict | None = None, retries: int = 4) -> object:
    for attempt in range(retries):
        try:
            resp = _SESSION.get(f"{BASE}{path}", params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def state() -> dict:
    """Current season and week, e.g. {"season": "2026", "week": 7, ...}."""
    return _get("/v1/state/nfl")


def players() -> dict:
    path = config.CACHE_DIR / "sleeper_players.json"
    if path.exists() and time.time() - path.stat().st_mtime < 24 * 3600:
        return json.loads(path.read_text())
    data = _get("/v1/players/nfl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def players_frame() -> pd.DataFrame:
    rows = []
    for pid, p in players().items():
        if not p:
            continue
        rows.append(
            {
                "sleeper_id": pid,
                "name": p.get("full_name")
                or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
                or pid,
                "position": p.get("position"),
                "sleeper_team": p.get("team"),
                "team": TEAM_TO_NFLVERSE.get(p.get("team"), p.get("team")),
                "injury_status": p.get("injury_status"),
                "status": p.get("status"),
                "gsis_id": (p.get("gsis_id") or "").strip() or None,
            }
        )
    return pd.DataFrame(rows)


def league(league_id: str) -> dict:
    return _get(f"/v1/league/{league_id}")


def rosters(league_id: str) -> list[dict]:
    return _get(f"/v1/league/{league_id}/rosters")


def users(league_id: str) -> list[dict]:
    return _get(f"/v1/league/{league_id}/users")


def projections(season: int, week: int) -> list[dict]:
    return _get(f"/projections/nfl/{season}/{week}", params={"season_type": "regular"})


def trending_adds(hours: int = 24, limit: int = 200) -> dict[str, int]:
    rows = _get("/v1/players/nfl/trending/add", params={"lookback_hours": hours, "limit": limit})
    return {r["player_id"]: r["count"] for r in rows}


def score_projection(stats: dict, scoring: dict[str, float]) -> float:
    """Sleeper projection stats are keyed like scoring_settings, so scoring is a dot product."""
    return float(sum(v * scoring.get(k, 0.0) for k, v in stats.items() if isinstance(v, (int, float))))
