"""Game lines from Kalshi's NFL markets (public, no auth).

Kalshi lists each game as ladders of binary markets: "PHI wins by over 3.5"
(KXNFLSPREAD), "Over 44.5 points" (KXNFLTOTAL), plus one winner market per team
(KXNFLGAME). A market's mid price is the market's probability of clearing that
strike, so the strike where the probability crosses 50% is the market's median:
the spread or total line. Winner prices, normalized across the two teams, give
the win probability.

Live projections (`lines_for_games`) and the line recorder (`record.py`) both
use `snapshot()`, so recorded and live lines are computed the same way.
"""

import re
from datetime import UTC, date, datetime
from itertools import pairwise

import pandas as pd
import requests

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = ("KXNFLSPREAD", "KXNFLTOTAL", "KXNFLGAME")
# nflverse team code -> Kalshi team code, where they differ
NFLVERSE_TO_KALSHI = {"LA": "LAR", "JAX": "JAC"}
_EVENT_RE = re.compile(r"^(?P<date>\d{2}[A-Z]{3}\d{2})(?P<teams>[A-Z]+)$")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1
    )
}


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


def _num(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ts(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def event_date(event: str) -> date | None:
    """26OCT26DALPHI -> 2026-10-26 (Kalshi's game date, Eastern)."""
    m = _EVENT_RE.match(event)
    if not m:
        return None
    d = m["date"]
    return date(2000 + int(d[:2]), _MONTHS[d[2:5]], int(d[5:]))


def market_rows(series: str, markets: list[dict], snapshot_at: datetime) -> list[dict]:
    """One row per market: the raw observation the recorder stores."""
    rows = []
    for m in markets:
        event = m["event_ticker"].split("-", 1)[1]
        suffix = m["ticker"].rsplit("-", 1)[1]
        rows.append(
            {
                "snapshot_at": snapshot_at,
                "series": series,
                "event": event,
                "ticker": m["ticker"],
                # Spread and winner tickers end in the team (PHI8, PHI); totals in the strike (45)
                "team": None if series == "KXNFLTOTAL" else re.sub(r"\d+$", "", suffix),
                "floor_strike": _num(m.get("floor_strike")),
                "yes_bid": _num(m.get("yes_bid_dollars")),
                "yes_ask": _num(m.get("yes_ask_dollars")),
                "last_price": _num(m.get("last_price_dollars")),
                "volume": _num(m.get("volume_fp")),
                "open_interest": _num(m.get("open_interest_fp")),
                "status": m.get("status"),
                "occurrence_at": _ts(m.get("occurrence_datetime")),
                "close_at": _ts(m.get("close_time")),
            }
        )
    return rows


def ladder_median(points: list[tuple[float, float]]) -> float | None:
    """points: (strike, P(value > strike)). Linear interpolation where P crosses 0.5."""
    pts = sorted(points)
    for (x1, p1), (x2, p2) in pairwise(pts):
        if p1 >= 0.5 >= p2 and p1 != p2:
            return x1 + (p1 - 0.5) / (p1 - p2) * (x2 - x1)
    return None


def game_lines(markets: pd.DataFrame) -> pd.DataFrame:
    """One row per event in a snapshot: away and home (Kalshi codes), the home
    team's median margin, the median total, and the home win probability."""
    m = markets.copy()
    m["mid"] = (m["yes_bid"] + m["yes_ask"]) / 2
    m = m[(m["yes_bid"] > 0) & (m["yes_ask"] > 0)]
    rows = []
    for event, grp in m.groupby("event"):
        match = _EVENT_RE.match(event)
        teams = sorted(set(grp["team"].dropna()))
        if not match or len(teams) != 2:
            continue
        a, b = teams
        if match["teams"] == a + b:
            away, home = a, b
        elif match["teams"] == b + a:
            away, home = b, a
        else:
            continue
        spread = grp[grp["series"] == "KXNFLSPREAD"]
        # Home ladder gives P(home margin > x); away ladder P(away margin > x) = P(home margin < -x)
        margin = [
            (x, p) if t == home else (-x, 1 - p)
            for t, x, p in zip(spread["team"], spread["floor_strike"], spread["mid"])
        ]
        total = grp[grp["series"] == "KXNFLTOTAL"]
        winner = grp[grp["series"] == "KXNFLGAME"].groupby("team")["mid"].mean()
        win_home = None
        if {home, away} <= set(winner.index) and winner[home] + winner[away] > 0:
            win_home = float(winner[home] / (winner[home] + winner[away]))  # removes the vig
        rows.append(
            {
                "snapshot_at": grp["snapshot_at"].iloc[0],
                "event": event,
                "event_date": event_date(event),
                "away": away,
                "home": home,
                "home_spread": ladder_median(margin),
                "total": ladder_median(list(zip(total["floor_strike"], total["mid"]))),
                "home_win_prob": win_home,
                "spread_markets": len(spread),
                "total_markets": len(total),
                "game_end_at": grp["occurrence_at"].max(),
            }
        )
    return pd.DataFrame(rows)


def snapshot(at: datetime | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every open NFL market now, and the game lines derived from them."""
    at = at or datetime.now(UTC)
    rows = [row for series in SERIES for row in market_rows(series, _markets(series), at)]
    markets = pd.DataFrame(rows)
    return markets, (game_lines(markets) if not markets.empty else pd.DataFrame())


def lines_for_games(games: pd.DataFrame) -> pd.DataFrame:
    """games: one row per game with game_id, home_team, away_team (nflverse codes).
    Returns game_id, spread_line (home margin), total_line from Kalshi where listed."""
    _, lines = snapshot()
    cols = ["game_id", "spread_line", "total_line"]
    if lines.empty:
        return pd.DataFrame(columns=cols)
    by_teams = {(r.away, r.home): r for r in lines.itertuples()}
    out = []
    for g in games.itertuples():
        r = by_teams.get(
            (
                NFLVERSE_TO_KALSHI.get(g.away_team, g.away_team),
                NFLVERSE_TO_KALSHI.get(g.home_team, g.home_team),
            )
        )
        if r is not None:
            out.append({"game_id": g.game_id, "spread_line": r.home_spread, "total_line": r.total})
    return pd.DataFrame(out, columns=cols)
