"""Questionable players: chance to play and production when playing (decision 0017).

The last practice before a game separates Questionable players sharply: regulars who did not
practice played about 45% of the time, limited about 71%, full about 80-88%. Those who played
also scored less than healthy players against the same projection. For each practice status:

    play  = share of Questionable regulars who played
    mult  = (actual / projected among those who played) / (the same ratio for healthy regulars)

fit on the availability tuning seasons (2016-2018). A Questionable player's projection is
multiplied by play x mult; ranges give him 0 points in a 1 - play share of simulated games.
"Regulars" played their team's previous game, so backups with stale Questionable tags do not
set the rates.
"""

import pandas as pd

FIT_SEASONS = range(2016, 2019)
PRACTICE = ("DNP", "Limited", "Full")
MIN_ROWS = 30  # fewer Questionable regulars than this for a practice status -> pooled rate


def previous_played(status: pd.DataFrame) -> pd.Series:
    """True when the player played his team's previous game (status rows, any order)."""
    s = status.sort_values(["gsis_id", "team", "kickoff_utc"])
    prev = s.groupby(["gsis_id", "team"])["played"].shift(1)
    return prev.eq(True).reindex(status.index)


def practice_key(df: pd.DataFrame) -> pd.Series:
    """DNP, Limited or Full for Questionable rows with a practice status, "all" for Questionable
    rows without one, None for everyone else."""
    q = df["injury_status"].eq("Questionable")
    key = df["practice_status"].where(df["practice_status"].isin(PRACTICE), "all")
    return key.where(q, None)


def fit(rows: pd.DataFrame, projection: str = "opp_points") -> dict[str, dict[str, float]]:
    """rows: expected-to-play player-games on the fit seasons, including those who sat (played
    0, fantasy_points 0), with injury_status, practice_status, regular and `projection`."""
    reg = rows[rows["regular"]]
    healthy = reg[reg["injury_status"].isna() & reg["played"].eq(1)]
    base = healthy["fantasy_points"].sum() / healthy[projection].sum()
    q = reg[reg["injury_status"].eq("Questionable")]

    def rates(g: pd.DataFrame) -> dict[str, float]:
        played = g[g["played"].eq(1)]
        mult = played["fantasy_points"].sum() / played[projection].sum() / base
        return {"play": round(float(g["played"].mean()), 3), "mult": round(float(mult), 3), "n": len(g)}

    table = {"all": rates(q)}
    keys = practice_key(q)
    for key in PRACTICE:
        g = q[keys == key]
        table[key] = rates(g) if len(g) >= MIN_ROWS else table["all"]
    return table


def factors(df: pd.DataFrame, table: dict[str, dict[str, float]] | None) -> tuple[pd.Series, pd.Series]:
    """(chance to play, production multiplier when playing) per row: 1 and 1 for everyone
    but Questionable players."""
    play = pd.Series(1.0, index=df.index)
    mult = pd.Series(1.0, index=df.index)
    if not table:
        return play, mult
    keys = practice_key(df)
    for key, rates in table.items():
        hit = keys == key
        play[hit], mult[hit] = rates["play"], rates["mult"]
    return play, mult
