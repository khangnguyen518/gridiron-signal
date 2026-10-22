"""League scoring. Projections are stat lines; any Sleeper league's scoring_settings
turns them into points, so one projection serves every league."""

import pandas as pd

# Our stat column -> Sleeper scoring_settings key
STAT_KEYS: dict[str, str] = {
    "pass_yards": "pass_yd",
    "pass_tds": "pass_td",
    "interceptions": "pass_int",
    "pass_2pt": "pass_2pt",
    "rush_yards": "rush_yd",
    "rush_tds": "rush_td",
    "rush_2pt": "rush_2pt",
    "receptions": "rec",
    "rec_yards": "rec_yd",
    "rec_tds": "rec_td",
    "rec_2pt": "rec_2pt",
    "fumbles_lost": "fum_lost",
}

# Full PPR, 4-point passing TD: the league this repo was built against.
DEFAULT_SCORING: dict[str, float] = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "pass_2pt": 2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rush_2pt": 2.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rec_2pt": 2.0,
    "fum_lost": -2.0,
}

# Position-specific bonuses Sleeper supports (TE premium, etc.): key -> (position, base stat)
POSITION_BONUSES: dict[str, tuple[str, str]] = {
    "bonus_rec_te": ("TE", "receptions"),
    "bonus_rec_rb": ("RB", "receptions"),
    "bonus_rec_wr": ("WR", "receptions"),
}


def fantasy_points(stats: pd.DataFrame, scoring: dict[str, float] | None = None) -> pd.Series:
    """Points for each row of stat columns. Missing columns count as zero.
    Yardage bonuses (100-yard games etc.) are not modeled."""
    scoring = scoring or DEFAULT_SCORING
    points = pd.Series(0.0, index=stats.index)
    for col, key in STAT_KEYS.items():
        if col in stats and scoring.get(key):
            points += stats[col].fillna(0).astype(float) * scoring[key]
    if "position" in stats:
        for key, (position, col) in POSITION_BONUSES.items():
            if scoring.get(key) and col in stats:
                is_pos = stats["position"] == position
                points += stats[col].fillna(0).astype(float).where(is_pos, 0.0) * scoring[key]
    return points
