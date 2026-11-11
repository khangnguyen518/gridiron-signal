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
    # Kickers and team defenses (decision 0021): Sleeper's defaults, used when no league is given
    "fgm_0_19": 3.0,
    "fgm_20_29": 3.0,
    "fgm_30_39": 3.0,
    "fgm_40_49": 4.0,
    "fgm_50p": 5.0,
    "fgmiss": -1.0,
    "xpm": 1.0,
    "xpmiss": -1.0,
    "pts_allow_0": 10.0,
    "pts_allow_1_6": 7.0,
    "pts_allow_7_13": 4.0,
    "pts_allow_14_20": 1.0,
    "pts_allow_21_27": 0.0,
    "pts_allow_28_34": -1.0,
    "pts_allow_35p": -4.0,
    "sack": 1.0,
    "int": 2.0,
    "fum_rec": 2.0,
    "ff": 1.0,
    "def_td": 6.0,
    "safe": 2.0,
    "blk_kick": 2.0,
    "st_fum_rec": 1.0,
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
