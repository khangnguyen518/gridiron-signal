"""Live game lines from Kalshi spread and total ladders (public, no auth).

Kalshi lists each game as a ladder of binary markets: "PHI wins by over 3.5",
"Over 44.5 points", and so on. Each market's mid price is the market's
probability of clearing that strike, so the strike where the probability
crosses 50% is the market's median: the spread or total line.
"""

import re
from itertools import pairwise

import pandas as pd
import requests

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
# nflverse team code -> Kalshi team code, where they differ
NFLVERSE_TO_KALSHI = {"LA": "LAR", "JAX": "JAC"}
_EVENT_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}(?P<teams>[A-Z]+)$")


def _markets(series: str) -> list[dict]:
    out, cursor = [], None
    while True:
        params = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{KALSHI_BASE}/markets", params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        out.extend(body.get("markets", []))
        cursor = body.get("cursor")
        if not cursor:
            return out


def _mid(m: dict) -> float | None:
    bid, ask = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
    if ask <= 0 or bid <= 0:
        return None
    return (bid + ask) / 2


def ladder_median(points: list[tuple[float, float]]) -> float | None:
    """points: (strike, P(value > strike)). Linear interpolation where P crosses 0.5."""
    pts = sorted(points)
    for (x1, p1), (x2, p2) in pairwise(pts):
        if p1 >= 0.5 >= p2 and p1 != p2:
            return x1 + (p1 - 0.5) / (p1 - p2) * (x2 - x1)
    return None


def kalshi_lines() -> pd.DataFrame:
    """One row per open Kalshi NFL game: event teams string (away+home, Kalshi codes),
    home margin median, total median."""
    totals: dict[str, list] = {}
    for m in _markets("KXNFLTOTAL"):
        p = _mid(m)
        if p is not None and m.get("floor_strike") is not None:
            totals.setdefault(m["event_ticker"].split("-", 1)[1], []).append((float(m["floor_strike"]), p))

    spreads: dict[str, list] = {}
    for m in _markets("KXNFLSPREAD"):
        p = _mid(m)
        if p is None or m.get("floor_strike") is None:
            continue
        event = m["event_ticker"].split("-", 1)[1]
        team = re.sub(r"\d+$", "", m["ticker"].rsplit("-", 1)[1])
        spreads.setdefault(event, []).append((team, float(m["floor_strike"]), p))

    rows = []
    for event in set(totals) | set(spreads):
        match = _EVENT_RE.match(event)
        if not match:
            continue
        rows.append(
            {
                "event": event,
                "teams": match["teams"],
                "total_points": totals.get(event, []),
                "spread_points": spreads.get(event, []),
            }
        )
    return pd.DataFrame(rows)


def lines_for_games(games: pd.DataFrame) -> pd.DataFrame:
    """games: one row per game with game_id, home_team, away_team (nflverse codes).
    Returns game_id, spread_line (home margin), total_line from Kalshi where listed."""
    kalshi = kalshi_lines()
    if kalshi.empty:
        return pd.DataFrame(columns=["game_id", "spread_line", "total_line"])
    by_teams = {r.teams: r for r in kalshi.itertuples()}
    out = []
    for g in games.itertuples():
        away = NFLVERSE_TO_KALSHI.get(g.away_team, g.away_team)
        home = NFLVERSE_TO_KALSHI.get(g.home_team, g.home_team)
        r = by_teams.get(away + home)
        if r is None:
            continue
        # Home ladder gives P(home margin > x); away ladder P(away margin > x) = P(home margin < -x)
        margin = [
            (x, p) if team == home else (-x, 1 - p) for team, x, p in r.spread_points if team in (home, away)
        ]
        out.append(
            {
                "game_id": g.game_id,
                "spread_line": ladder_median(margin),
                "total_line": ladder_median(r.total_points),
            }
        )
    return pd.DataFrame(out, columns=["game_id", "spread_line", "total_line"])
