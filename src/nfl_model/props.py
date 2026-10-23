"""Player props from Kalshi's NFL markets (public, no auth), recorded hourly (decision 0015).

Each prop is a ladder of binary markets, like the game lines in `lines.py`: "Brock Purdy:
175+ passing yards" (KXNFLPASSYDS, floor_strike 174.5) is P(yards > 174.5). Tickers carry
the game, the player's team and a player code: KXNFLRECYDS-26OCT25TBCAR-CARJMETCHIE13-40.

Only raw markets are stored here. Matching players to gsis IDs and turning ladders into
medians is left to whatever reads the history, so the raw rows keep every input.
"""

from datetime import datetime

import pandas as pd

from nfl_model.lines import _EVENT_RE, _markets, _num, _ts

SERIES = (
    "KXNFLTD",  # 1+, 2+, 3+ touchdowns
    "KXNFLFIRSTTD",  # first touchdown scorer (no strike)
    "KXNFLRECYDS",
    "KXNFLREC",
    "KXNFLRSHYDS",
    "KXNFLRSHATT",
    "KXNFLRRYDS",  # rushing plus receiving yards
    "KXNFLPASSYDS",
    "KXNFLPASSTDS",
    "KXNFLPASSATT",
    "KXNFLPASSCOMP",
    "KXNFLPASSINT",
    "KXNFLFFPTS",  # player and D/ST fantasy points, over a line
    "KXNFLTEAMTOTAL",  # team points, no player
)
# Kalshi team codes (nflverse codes with LA -> LAR and JAX -> JAC, as in lines.NFLVERSE_TO_KALSHI)
TEAMS = frozenset(
    [
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "HOU",
        "IND",
        "JAC",
        "KC",
        "LAC",
        "LAR",
        "LV",
        "MIA",
        "MIN",
        "NE",
        "NO",
        "NYG",
        "NYJ",
        "PHI",
        "PIT",
        "SEA",
        "SF",
        "TB",
        "TEN",
        "WAS",
    ]
)


def event_teams(event: str) -> tuple[str, str] | None:
    """26OCT25LARLV -> (LAR, LV): away and home, split where both halves are team codes."""
    m = _EVENT_RE.match(event)
    if not m:
        return None
    teams = m["teams"]
    splits = [(teams[:k], teams[k:]) for k in (2, 3) if teams[:k] in TEAMS and teams[k:] in TEAMS]
    return splits[0] if len(splits) == 1 else None


def selection_team(event: str, selection: str) -> str | None:
    """The team a market is about: which of the game's two codes its selection starts with
    (LARJWHITTINGTON88 in LAR at LV -> LAR)."""
    teams = event_teams(event)
    if teams is None:
        return None
    hits = [t for t in teams if selection.startswith(t)]
    return max(hits, key=len) if hits else None


def player_name(market: dict) -> str | None:
    """Text before the colon in the subtitle ("Brock Purdy: 175+"), or the whole subtitle
    for first-TD markets. None for team totals, which have no player."""
    if "football_player" not in (market.get("custom_strike") or {}):
        return None
    sub = market.get("yes_sub_title") or market.get("title") or ""
    return sub.split(":", 1)[0].strip() or None


def prop_rows(series: str, markets: list[dict], snapshot_at: datetime) -> list[dict]:
    """One row per market: the raw observation the recorder stores."""
    rows = []
    for m in markets:
        event = m["event_ticker"].split("-", 1)[1]
        parts = m["ticker"].split("-")
        rows.append(
            {
                "snapshot_at": snapshot_at,
                "series": series,
                "event": event,
                "ticker": m["ticker"],
                "team": selection_team(event, parts[2]) if len(parts) > 2 else None,
                "player": player_name(m),
                "kalshi_player_id": (m.get("custom_strike") or {}).get("football_player"),
                "floor_strike": _num(m.get("floor_strike")),
                "strike_type": m.get("strike_type"),
                "yes_bid": _num(m.get("yes_bid_dollars")),
                "yes_ask": _num(m.get("yes_ask_dollars")),
                "last_price": _num(m.get("last_price_dollars")),
                "volume": _num(m.get("volume_fp")),
                "open_interest": _num(m.get("open_interest_fp")),
                "status": m.get("status"),
                "occurrence_at": _ts(m.get("occurrence_datetime")),
                "close_at": _ts(m.get("close_time")),
                "title": m.get("title"),
            }
        )
    return rows


def snapshot(at: datetime) -> pd.DataFrame:
    """Every open NFL player-prop market now, every page."""
    return pd.DataFrame([row for series in SERIES for row in prop_rows(series, _markets(series), at)])
