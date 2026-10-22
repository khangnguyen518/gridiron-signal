"""Connect a Sleeper league: best lineup, close start/sit calls, and waiver targets
for one week, scored with the league's own scoring settings.

    uv run nflm league --league-id 123 --user "display name" --week 7

Projection per player:
    blend = w * ours + (1 - w) * Sleeper, with w per position from the backtest.
    Only one source available -> that source. Out / IR / suspended / bye -> 0.
Kickers and defenses use Sleeper's projection only.
"""

from datetime import datetime

import numpy as np
import pandas as pd

from nfl_model import config, sleeper
from nfl_model.live import project_week

SLOT_ELIGIBLE: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
OUT_STATUSES = {"Out", "IR", "PUP", "Sus", "NA", "DNR"}
CLOSE_CALL_POINTS = 2.0


def build_player_table(season: int, week: int, scoring: dict[str, float]) -> tuple[pd.DataFrame, list[str]]:
    """Every fantasy-relevant player with ours, Sleeper and blended projections."""
    ours, notes = project_week(season, week, scoring)
    ours = ours[
        [
            "sleeper_id",
            "opponent",
            "implied_points",
            "spread",
            "line_source",
            "opp_points",
            "blend_w",
            "target_share",
            "carry_share",
            "targets_hat",
            "carries_hat",
            "target_share_scale",
            "carry_share_scale",
            "att_share_scale",
        ]
    ]
    ours = ours.rename(columns={"opp_points": "ours"}).dropna(subset=["sleeper_id"])

    sl = pd.DataFrame(
        [
            {
                "sleeper_id": p["player_id"],
                "sleeper": sleeper.score_projection(p.get("stats") or {}, scoring),
                "sleeper_opponent": p.get("opponent"),
            }
            for p in sleeper.projections(season, week)
        ]
    )
    players = sleeper.players_frame()
    players = players[players["position"].isin(set(config.POSITIONS) | {"K", "DEF"})]
    df = players.merge(sl, on="sleeper_id", how="left").merge(ours, on="sleeper_id", how="left")
    df = df[df["sleeper"].notna() | df["ours"].notna()]

    w = df["blend_w"].fillna(0.0)
    df["proj"] = np.where(
        df["ours"].notna() & df["sleeper"].notna(),
        w * df["ours"] + (1 - w) * df["sleeper"],
        df["sleeper"].fillna(df["ours"]),
    )
    df["opponent"] = df["opponent"].fillna(df["sleeper_opponent"])
    df["flag"] = ""
    df.loc[df["ours"].isna() & df["position"].isin(config.POSITIONS), "flag"] = "no history: Sleeper only"
    is_out = df["injury_status"].isin(OUT_STATUSES)
    df.loc[is_out, "flag"] = df.loc[is_out, "injury_status"]
    df.loc[df["injury_status"].isin({"Questionable", "Doubtful"}), "flag"] = df["injury_status"]
    on_bye = df["opponent"].isna()
    df.loc[on_bye, "flag"] = "bye"
    df.loc[is_out | on_bye, "proj"] = 0.0
    df["proj"] = df["proj"].round(2)
    return df.drop(columns=["sleeper_opponent"]), notes


def optimal_lineup(roster: pd.DataFrame, slots: list[str]) -> pd.DataFrame:
    """Fill the most restrictive slots first with the best eligible player. For Sleeper's
    nested slot types (position, flex, superflex) this greedy order is optimal."""
    order = sorted(slots, key=lambda s: len(SLOT_ELIGIBLE.get(s, {s})))
    pool = roster.sort_values("proj", ascending=False).copy()
    picks = []
    for slot in order:
        eligible = pool[pool["position"].isin(SLOT_ELIGIBLE.get(slot, {slot}))]
        if eligible.empty:
            picks.append({"slot": slot})
            continue
        best = eligible.iloc[0]
        picks.append({"slot": slot, **best.to_dict()})
        pool = pool.drop(best.name)
    lineup = pd.DataFrame(picks)
    lineup["slot"] = pd.Categorical(lineup["slot"], categories=list(dict.fromkeys(slots)), ordered=True)
    return lineup.sort_values(["slot", "proj"], ascending=[True, False])


def close_calls(lineup: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    """Bench players projected within 2 points of a starter whose slot they could fill."""
    rows = []
    for s in lineup.dropna(subset=["sleeper_id"]).itertuples():
        for b in bench.itertuples():
            if (
                b.position in SLOT_ELIGIBLE.get(s.slot, {s.slot})
                and abs(s.proj - b.proj) <= CLOSE_CALL_POINTS
            ):
                rows.append(
                    {
                        "slot": s.slot,
                        "start": s.name,
                        "start_proj": s.proj,
                        "bench": b.name,
                        "bench_proj": b.proj,
                        "gap": round(s.proj - b.proj, 2),
                    }
                )
    return pd.DataFrame(rows)


def waiver_targets(
    players: pd.DataFrame, rostered: set[str], lineup: pd.DataFrame, per_pos: int = 8
) -> pd.DataFrame:
    """Unrostered players by this week's projection, with the gain over the weakest
    starter they could replace, recent usage, and Sleeper's 24-hour add trend."""
    trending = sleeper.trending_adds()
    free = players[
        ~players["sleeper_id"].isin(rostered) & ~players["flag"].isin(OUT_STATUSES | {"bye"})
    ].copy()
    free["adds_24h"] = free["sleeper_id"].map(trending).fillna(0).astype(int)

    starters = lineup.dropna(subset=["sleeper_id"])

    def weakest(position: str) -> float:
        can = starters[[position in SLOT_ELIGIBLE.get(s, {s}) for s in starters["slot"]]]
        return float(can["proj"].min()) if not can.empty else 0.0

    free["upgrade"] = (free["proj"] - free["position"].map(weakest)).round(2)
    free = free.sort_values("proj", ascending=False).groupby("position").head(per_pos)
    return free.sort_values(["upgrade", "proj"], ascending=False)


def find_roster(rosters: list[dict], users: list[dict], user: str | None) -> dict:
    names = {u["user_id"]: (u.get("display_name") or "") for u in users}
    if user:
        for r in rosters:
            if names.get(r.get("owner_id"), "").lower() == user.lower():
                return r
    teams = ", ".join(sorted(n for n in names.values() if n))
    raise SystemExit(f"Pick your team with --user (or SLEEPER_USERNAME in .env). Teams: {teams}")


def discord_summary(
    league_name: str,
    season: int,
    week: int,
    lineup: pd.DataFrame,
    calls: pd.DataFrame,
    waivers: pd.DataFrame,
    notes: list[str],
) -> str:
    """Short text version of the lineup, close calls and top waiver targets."""
    lines = [f"**{league_name} | {season} week {week}** (projected {lineup['proj'].sum():.1f})", "```"]
    for r in lineup.itertuples():
        flag = f"  [{r.flag}]" if isinstance(r.flag, str) and r.flag else ""
        name = r.name if isinstance(r.name, str) else "(empty)"
        lines.append(f"{r.slot:<10} {name:<22} {r.proj:5.1f}{flag}")
    lines.append("```")
    if not calls.empty:
        lines.append("**Close calls**")
        lines += [
            f"- {c.slot}: {c.start} {c.start_proj:.1f} vs {c.bench} {c.bench_proj:.1f}"
            for c in calls.itertuples()
        ]
    top = waivers[waivers["upgrade"] > 0].head(5)
    if not top.empty:
        lines.append("**Waiver upgrades**")
        lines += [
            f"- {w.name} ({w.position}, {w.sleeper_team}) {w.proj:.1f}, +{w.upgrade:.1f}"
            for w in top.itertuples()
        ]
    lines += [f"_{n}_" for n in notes]
    return "\n".join(lines)


def run(league_id: str, user: str | None, week: int | None, discord: bool = False) -> None:
    lg = sleeper.league(league_id)
    st = sleeper.state()
    season = int(lg.get("season") or st["season"])
    week = week or int(st["week"])
    scoring = {k: float(v) for k, v in (lg.get("scoring_settings") or {}).items()}
    slots = [s for s in lg.get("roster_positions", []) if s not in {"BN", "IR", "TAXI"}]

    rosters, users = sleeper.rosters(league_id), sleeper.users(league_id)
    mine = find_roster(rosters, users, user)
    rostered = {p for r in rosters for p in (r.get("players") or [])}

    print(f"{lg.get('name')} | {season} week {week} | scoring from the league's settings")
    players, notes = build_player_table(season, week, scoring)
    for note in notes:
        print(f"Note: {note}")

    roster = players[players["sleeper_id"].isin(mine.get("players") or [])]
    lineup = optimal_lineup(roster, slots)
    bench = roster[~roster["sleeper_id"].isin(lineup["sleeper_id"])].sort_values("proj", ascending=False)
    calls = close_calls(lineup, bench)
    waivers = waiver_targets(players, rostered, lineup)

    cols = [
        "name",
        "position",
        "sleeper_team",
        "opponent",
        "proj",
        "ours",
        "sleeper",
        "implied_points",
        "flag",
    ]
    pd.set_option("display.width", 180)
    print("\n=== Best lineup ===")
    print(lineup[["slot"] + cols].round(2).to_string(index=False))
    print(f"Projected total: {lineup['proj'].sum():.1f}")
    print("\n=== Bench ===")
    print(bench[cols].round(2).to_string(index=False))
    print("\n=== Close calls (within 2 points) ===")
    print(calls.to_string(index=False) if not calls.empty else "None: every start is clear.")
    print("\n=== Waiver targets ===")
    wcols = [
        "name",
        "position",
        "sleeper_team",
        "opponent",
        "proj",
        "upgrade",
        "target_share",
        "carry_share",
        "adds_24h",
        "flag",
    ]
    print(waivers[wcols].head(20).round(2).to_string(index=False))

    out = config.OUTPUT_DIR / "league" / f"{league_id}_{season}_w{week:02d}_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    lineup.to_csv(out / "lineup.csv", index=False)
    bench.to_csv(out / "bench.csv", index=False)
    calls.to_csv(out / "close_calls.csv", index=False)
    waivers.to_csv(out / "waivers.csv", index=False)
    players.to_csv(out / "all_projections.csv", index=False)
    print(f"\nWrote {out}")

    if discord:
        from nfl_model import alerts

        alerts.send(discord_summary(lg.get("name") or league_id, season, week, lineup, calls, waivers, notes))
