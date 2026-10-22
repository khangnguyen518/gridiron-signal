"""Who is expected to play, and renormalizing usage shares to match.

A player's recent share says nothing about who else plays this week. When a
starter is out, the shares of the players left add up to less than usual, and
someone absorbs the rest. When a starter returns, his teammates' shares
(inflated while he was out) add up to more than usual.

Targets and carries, per team-game and position group (a missing WR's targets
mostly go to the other WRs):

    S      = sum of shares over players at that position expected to play
    usual  = this team's recent share of targets (or carries) going to that position,
             recency-weighted over its earlier games, times a small factor for the
             stale shares every S carries (median S / usual over the tuning seasons)
    scale  = clip((usual / S) ^ beta)

Comparing with the team's own usual total keeps team style intact: a team that
throws to its TEs, or whose QB runs, is not pushed toward the league average.
Only RB, WR and TE targets and RB carries are adjusted. A backup QB does not
inherit the starter's rushing.

Pass attempts, per team-game: S is the top attempt share among QBs expected to
play, and center is a usual starter's share (about 0.99). A backup with a 4%
share becomes the starter when the starter is out. A sum would not work here:
backups keep large shares from old spot starts.

beta = 0 turns a type off; beta = 1 restores the usual total fully. Players out
for a few games are already absorbed by their teammates' recent shares, so they
move S little. Red-zone shares scale with their base share.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nfl_model.features import lagged_wsum

RZ_SHARE = {"target_share": "rz_target_share", "carry_share": "rz_carry_share"}
# Position groups renormalized per share type. Others (a QB's targets, a TE's carries) are
# too rare to have a usual total and keep scale 1.
GROUPS = {"target_share": {"RB", "WR", "TE"}, "carry_share": {"RB"}}
# share column -> (player stat, team stat) that defines it
SHARE_STATS = {
    "target_share": ("targets", "team_pass_attempts"),
    "carry_share": ("carries", "team_rush_attempts"),
}
CLIPS: dict[str, tuple[float, float]] = {
    "target_share": (0.5, 2.0),
    "carry_share": (0.5, 2.0),
    "att_share": (0.5, 40.0),  # a backup QB can go from 3% to 100% of attempts
}
# Shares big enough that losing the player changes the offense (for reporting)
KEY_SHARE = {"target_share": 0.15, "carry_share": 0.30, "att_share": 0.50}


@dataclass(frozen=True)
class Renorm:
    beta_target: float = 0.0
    beta_carry: float = 0.0
    beta_att: float = 0.0


ZERO_COLS = [
    "pass_attempts",
    "completions",
    "pass_yards",
    "pass_tds",
    "interceptions",
    "pass_2pt",
    "carries",
    "rush_yards",
    "rush_tds",
    "rush_2pt",
    "targets",
    "receptions",
    "rec_yards",
    "rec_tds",
    "rec_2pt",
    "air_yards",
    "fumbles_lost",
    "rz_targets",
    "rz_carries",
    "fantasy_points",
    "team_points",
    "team_pass_attempts",
    "team_rush_attempts",
    "team_rz_pass_attempts",
    "team_rz_rush_attempts",
]


def add_roster_rows(pg: pd.DataFrame, status: pd.DataFrame) -> pd.DataFrame:
    """Adds a placeholder row (played = 0, zero stats) for every rostered player who
    did not play, and the availability flags to every row. Players who played but
    have no roster row count as expected to play."""
    cols = ["game_id", "gsis_id", "expected_active_lock", "expected_active_midweek"]
    flags = status[cols + [c for c in ("depth_tier",) if c in status]]
    pg = pg.merge(flags, on=["game_id", "gsis_id"], how="left")
    for col in ["expected_active_lock", "expected_active_midweek"]:
        pg[col] = pg[col].fillna(True).astype(bool)

    missing = status[~status["played"].astype(bool)]
    missing = missing[missing["gsis_id"].isin(pg["gsis_id"])]  # only players with any NFL game
    keep = [
        "game_id",
        "season",
        "week",
        "kickoff_utc",
        "team",
        "gsis_id",
        "player_name",
        "position",
        "expected_active_lock",
        "expected_active_midweek",
    ]
    ph = missing[keep + [c for c in ("depth_tier",) if c in missing]].copy()
    ph[ZERO_COLS] = 0.0
    ph["played"] = 0.0
    return pd.concat([pg, ph], ignore_index=True)


def _active(feats: pd.DataFrame, flag: str) -> pd.Series:
    return feats[flag].astype(bool) & (feats["prior_games"] >= 1)


def add_team_usual(feats: pd.DataFrame, team_games: pd.DataFrame, half_life: float) -> pd.DataFrame:
    """Adds usual_target_share and usual_carry_share: the recency-weighted share of the
    team's targets (carries) that went to the row's position group in earlier games.
    team_games lists every team-game to cover (game_id, team, kickoff_utc)."""
    played = feats[feats["played"] == 1]
    grid = team_games[["game_id", "team", "kickoff_utc"]].drop_duplicates(["game_id", "team"])
    out = feats.copy()
    for share, (stat, team_stat) in SHARE_STATS.items():
        per_pos = (
            played.groupby(["game_id", "team", "position"])
            .agg(n=(stat, "sum"), d=(team_stat, "first"))
            .reset_index()
        )
        per_pos["frac"] = per_pos["n"] / per_pos["d"].replace(0, np.nan)
        rows = grid.merge(pd.DataFrame({"position": sorted(GROUPS[share])}), how="cross")
        rows = rows.merge(
            per_pos[["game_id", "team", "position", "frac"]], on=["game_id", "team", "position"], how="left"
        )
        rows = rows.sort_values(["team", "position", "kickoff_utc"]).reset_index(drop=True)
        step = rows["frac"].notna().astype(float)
        key = rows["team"] + "|" + rows["position"]
        games = lagged_wsum(step, key, half_life, step)
        rows[f"usual_{share}"] = lagged_wsum(rows["frac"], key, half_life, step) / games.replace(0, np.nan)
        out = out.drop(columns=[f"usual_{share}"], errors="ignore").merge(
            rows[["game_id", "team", "position", f"usual_{share}"]],
            on=["game_id", "team", "position"],
            how="left",
        )
    return out


def _group_total(feats: pd.DataFrame, share: str, active: pd.Series) -> pd.Series:
    keys = [feats["game_id"], feats["team"], feats["position"]]
    return feats[share].where(active, 0.0).groupby(keys).transform("sum")


def centers(feats: pd.DataFrame, flag: str, seasons: range | list[int]) -> dict:
    """Stale-share factor per position group (median of S / usual over team-games in
    `seasons`) and a usual starter's top QB attempt share."""
    active = _active(feats, flag)
    out: dict = {}
    for share in SHARE_STATS:
        total = _group_total(feats, share, active)
        rows = feats.assign(_total=total)[
            feats["season"].isin(seasons) & active & feats["position"].isin(GROUPS[share])
        ]
        rows = rows.drop_duplicates(["game_id", "team", "position"])
        ratio = rows["_total"] / rows[f"usual_{share}"].replace(0, np.nan)
        out[share] = {pos: float(r.median()) for pos, r in ratio.groupby(rows["position"])}
    qbs = feats[feats["season"].isin(seasons) & active & (feats["position"] == "QB")]
    out["att_share"] = float(qbs.groupby(["game_id", "team"])["att_share"].max().median())
    return out


def renormalize(feats: pd.DataFrame, flag: str, renorm: Renorm, center: dict) -> pd.DataFrame:
    """Scales each team-game's shares so players expected to play reach the team's usual
    totals. Needs usual_* columns from add_team_usual."""
    feats = feats.copy()
    active = _active(feats, flag)

    for share, beta in [("target_share", renorm.beta_target), ("carry_share", renorm.beta_carry)]:
        total = _group_total(feats, share, active)
        usual = feats[f"usual_{share}"] * feats["position"].map(center[share])
        scale = ((usual / total.replace(0, np.nan)) ** beta).fillna(1.0).clip(*CLIPS[share])
        scale = scale.where(feats["position"].isin(GROUPS[share]), 1.0)
        feats[f"{share}_scale"] = scale
        feats[share] = feats[share] * scale
        feats[RZ_SHARE[share]] = feats[RZ_SHARE[share]] * scale

    qb = active & (feats["position"] == "QB")
    top = feats["att_share"].where(qb, 0.0).groupby([feats["game_id"], feats["team"]]).transform("max")
    scale = ((center["att_share"] / top.replace(0, np.nan)) ** renorm.beta_att).fillna(1.0)
    feats["att_share_scale"] = scale.clip(*CLIPS["att_share"])
    feats["att_share"] = feats["att_share"] * feats["att_share_scale"]
    return feats


def key_absence(feats: pd.DataFrame, flag: str) -> pd.Series:
    """True for rows whose team is missing a player with a big recent share who
    played the team's previous game: a fresh absence the shares have not absorbed."""
    f = feats.sort_values(["team", "kickoff_utc"])
    team_games = f.drop_duplicates(["team", "game_id"])[["team", "game_id", "kickoff_utc"]]
    team_games = team_games.sort_values(["team", "kickoff_utc"])
    team_games["prev_game_id"] = team_games.groupby("team")["game_id"].shift(1)
    f = f.merge(team_games[["team", "game_id", "prev_game_id"]], on=["team", "game_id"], how="left")

    played_prev = set(
        zip(feats.loc[feats["played"] == 1, "game_id"], feats.loc[feats["played"] == 1, "gsis_id"])
    )
    out = ~f[flag] & (f["prior_games"] >= 1)
    out &= np.array([(p, g) in played_prev for p, g in zip(f["prev_game_id"], f["gsis_id"])])
    big = np.zeros(len(f), dtype=bool)
    for share, threshold in KEY_SHARE.items():
        raw = f[share] / f.get(f"{share}_scale", 1.0)
        big |= (raw >= threshold).to_numpy()
    f["_absent_key"] = out & big
    hit = f.groupby(["game_id", "team"])["_absent_key"].any()
    idx = pd.MultiIndex.from_frame(feats[["game_id", "team"]])
    return pd.Series(hit.reindex(idx).fillna(False).to_numpy(), index=feats.index)
