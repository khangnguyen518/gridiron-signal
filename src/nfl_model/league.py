"""Connect a Sleeper league: best lineup, close start/sit calls, and waiver targets
for one week, scored with the league's own scoring settings.

    uv run nflm league --league-id 123 --user "display name" --week 7

Projection per player:
    blend = w * ours + (1 - w) * Sleeper + shift + matchup, with w and the median shift per
    position from the backtest (decision 0016) and the opponent's points allowed to the
    player's position times a fitted weight (decision 0018).
    Only one source available -> that source. Out / IR / suspended / bye -> 0.
Kickers and defenses use Sleeper's projection only.

Ranges and win probability come from the game simulation (simulate.py): every player
gets draws centered on his blended projection before the median shift, with teammates and opponents sharing
game draws. Players the simulation cannot cover (kickers, defenses, rookies with no
NFL game) get Normal draws around the projection with a position spread.
"""

from datetime import datetime

import numpy as np
import pandas as pd

from nfl_model import config, sleeper
from nfl_model.live import load_model_card, project_week
from nfl_model.simulate import SimParams, mix_with_residuals, rescale, simulate, stretch_tails

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
N_SIMS = 1000  # memory: the shared VM has 1 GB; paired comparisons keep win-probability noise low
# Standard deviation of points for kickers and defenses, which have no simulation or history
# here: assumed, not backtested. Skill players without a simulation use historical misses.
FALLBACK_SD = {"K": 4.0, "DEF": 5.5}


def build_player_table(
    season: int, week: int, scoring: dict[str, float]
) -> tuple[pd.DataFrame, list[str], np.ndarray]:
    """Every fantasy-relevant player with ours, Sleeper and blended projections, plus
    simulated points (rows aligned with the table, N_SIMS columns)."""
    ours_full, notes = project_week(season, week, scoring)
    # Role this week (WR1, RB2, ...) from the depth chart and recent usage (roles.py)
    if "role" in ours_full:
        ours_full["role_label"] = [
            f"{p}{int(r)}" if pd.notna(r) else "" for p, r in zip(ours_full["position"], ours_full["role"])
        ]
    else:
        ours_full["role_label"] = ""
    ours = ours_full[
        [
            "sleeper_id",
            "role_label",
            "opponent",
            "implied_points",
            "spread",
            "line_source",
            "opp_points",
            "blend_w",
            "blend_shift",
            "blend_matchup",
            "q_play",
            "q_mult",
            "practice_status",
            "kickoff_utc",
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
    both = df["ours"].notna() & df["sleeper"].notna()
    shift = np.where(both, df["blend_shift"].fillna(0.0), 0.0)
    # Opponent points allowed to his position (decision 0018), only on blended rows like the shift
    match = np.where(both, df["blend_matchup"].fillna(0.0), 0.0)
    base = np.where(
        both, w * df["ours"] + (1 - w) * df["sleeper"] + shift + match, df["sleeper"].fillna(df["ours"])
    )
    # Questionable players (decision 0017): expected points = chance to play x production when playing
    q_play, q_mult = df["q_play"].fillna(1.0).to_numpy(), df["q_mult"].fillna(1.0).to_numpy()
    df["proj"] = base * q_play * q_mult
    df["opponent"] = df["opponent"].fillna(df["sleeper_opponent"])
    df["role_label"] = df["role_label"].replace("", np.nan).fillna(df["position"])  # K, DEF, no history
    df["flag"] = ""
    df.loc[df["ours"].isna() & df["position"].isin(config.POSITIONS), "flag"] = "no history: Sleeper only"
    is_out = df["injury_status"].isin(OUT_STATUSES)
    df.loc[is_out, "flag"] = df.loc[is_out, "injury_status"]
    df.loc[df["injury_status"].isin({"Questionable", "Doubtful"}), "flag"] = df["injury_status"]
    unsure = df["injury_status"].eq("Questionable") & (q_play < 1)
    df.loc[unsure, "flag"] = [f"Questionable, plays {p:.0%}" for p in q_play[unsure.to_numpy()]]
    on_bye = df["opponent"].isna()
    df.loc[on_bye, "flag"] = "bye"
    df.loc[is_out | on_bye, "proj"] = 0.0
    df["proj"] = df["proj"].round(2)
    # Ranges are centered on the blend before its median shift: the simulation sets each player's
    # mean, and the shifted blend estimates the median, which sits below it (decision 0016)
    # A Questionable player's draws are centered on his points if he plays, and are 0 in a 1 - q_play
    # share of games; "center" (lineup ranking, expected total) is the mean including the zeros
    df["center_play"] = np.where(df["proj"] > 0, (base - shift) * q_mult, 0.0)
    df["center"] = df["center_play"] * q_play
    df = df.drop(columns=["sleeper_opponent"]).reset_index(drop=True)

    draws = player_draws(df, ours_full, scoring)
    q = np.quantile(draws, [0.1, 0.5, 0.9], axis=1)
    df["p10"], df["p50"], df["p90"] = q[0].round(1), q[1].round(1), q[2].round(1)
    return df, notes, draws


def player_draws(df: pd.DataFrame, ours_full: pd.DataFrame, scoring: dict[str, float]) -> np.ndarray:
    """Simulated points per table row, centered on each row's center_play (the blend before its
    median shift, times a Questionable player's production if he plays). Zero for players who
    will not play, and for a Questionable player in a 1 - q_play share of games (decision 0017)."""
    seed = int(pd.Timestamp.now().strftime("%Y%m%d"))
    rng = np.random.default_rng(seed)
    draws = np.zeros((len(df), N_SIMS), dtype=np.float32)
    card = load_model_card()
    table = card.get("residual_table")
    sim_rows = ours_full.dropna(subset=["implied_points", "team_pass_attempts_hat", "sleeper_id"])
    sim_index: dict[str, int] = {}
    sim_draws = None
    if "sim" in card and not sim_rows.empty:
        sim_rows = sim_rows.reset_index(drop=True)
        sim_draws = simulate(sim_rows, SimParams(**card["sim"]), n=N_SIMS, scoring=scoring, seed=seed)
        sim_index = {sid: i for i, sid in enumerate(sim_rows["sleeper_id"])}
    for i, row in enumerate(df.itertuples()):
        if row.proj <= 0:
            continue
        j = sim_index.get(row.sleeper_id)
        if sim_draws is not None and j is not None:
            c, pos = np.array([row.center_play]), np.array([row.position])
            one = stretch_tails(rescale(sim_draws[j : j + 1], c), c, pos, card.get("sim_tails"))
            one = mix_with_residuals(one, c, pos, card.get("residual_table"), card.get("range_mix"))
            draws[i] = one[0]
        elif table and row.position in table["resid"]:
            # No simulation (no NFL game yet): historical misses for his position and projection level
            b = int(np.digitize(row.center_play, table["edges"]))
            draws[i] = row.center_play + np.interp(
                rng.random(N_SIMS), table["levels"], table["resid"][row.position][b]
            )
        else:
            sd = FALLBACK_SD.get(row.position, 6.0)
            draws[i] = np.maximum(row.center_play + sd * rng.standard_normal(N_SIMS), -4.0)
        q_play = getattr(row, "q_play", 1.0)
        if pd.notna(q_play) and q_play < 1:
            draws[i, rng.random(N_SIMS) >= q_play] = 0.0  # games he sits
    return draws


def win_probability(mine: list[int], theirs: list[int], draws: np.ndarray) -> float:
    """P(my lineup outscores theirs), ties split, from the same simulated games."""
    a = draws[mine].sum(axis=0) if mine else np.zeros(draws.shape[1])
    b = draws[theirs].sum(axis=0) if theirs else np.zeros(draws.shape[1])
    return float(np.mean(a > b) + 0.5 * np.mean(a == b))


def max_win_lineup(
    lineup: pd.DataFrame,
    bench: pd.DataFrame,
    theirs: list[int],
    draws: np.ndarray,
    players: pd.DataFrame,
    max_steps: int = 6,
) -> tuple[pd.DataFrame, list[tuple[str, str, str]], float]:
    """Starting from the best-projection lineup, repeatedly make the bench-for-starter swap
    that raises win probability most. Returns the lineup, the swaps (slot, in, out) and
    its win probability."""
    # zip, not itertuples: itertuples renames columns that start with an underscore
    slots = [(str(slot), None if pd.isna(i) else int(i)) for slot, i in zip(lineup["slot"], lineup["_i"])]
    pool = [int(i) for i, p in zip(bench["_i"], bench["proj"]) if p > 0]
    pos = players["position"].to_numpy()

    def starters(sl: list[tuple[str, int | None]]) -> list[int]:
        return [i for _, i in sl if i is not None]

    swaps = []
    current = win_probability(starters(slots), theirs, draws)
    for _ in range(max_steps):
        best = (current, None, None)
        for k, (slot, out) in enumerate(slots):
            for b in pool:
                if pos[b] not in SLOT_ELIGIBLE.get(slot, {slot}):
                    continue
                trial = slots.copy()
                trial[k] = (slot, b)
                p = win_probability(starters(trial), theirs, draws)
                if p > best[0] + 0.002:  # ignore simulation noise
                    best = (p, k, b)
        if best[1] is None:
            break
        current, k, b = best
        slot, out = slots[k]
        slots[k] = (slot, b)
        pool.remove(b)
        if out is not None:
            pool.append(out)
        swaps.append((slot, players.at[b, "name"], players.at[out, "name"] if out is not None else "(empty)"))
    rows = [
        {**players.loc[i].to_dict(), "slot": slot} if i is not None else {"slot": slot} for slot, i in slots
    ]
    return pd.DataFrame(rows), swaps, current


def optimal_lineup(roster: pd.DataFrame, slots: list[str]) -> pd.DataFrame:
    """Fill the most restrictive slots first with the best eligible player. For Sleeper's
    nested slot types (position, flex, superflex) this greedy order is optimal."""
    order = sorted(slots, key=lambda s: len(SLOT_ELIGIBLE.get(s, {s})))
    # Rank on the blend before its median shift: a lineup total sums means, and the shift differs
    # by position, so ranking on the shifted projection would tilt FLEX picks (decision 0016)
    key = "center" if "center" in roster else "proj"
    pool = roster.sort_values(key, ascending=False).copy()
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


def close_calls(
    lineup: pd.DataFrame,
    bench: pd.DataFrame,
    theirs: list[int] | None = None,
    draws: np.ndarray | None = None,
) -> pd.DataFrame:
    """Bench players projected within 2 points of a starter whose slot they could fill,
    with the matchup win probability either way when draws are given."""
    rows = []
    starters = [int(x) for x in lineup["_i"].dropna()] if "_i" in lineup else []
    # iterrows, not itertuples: itertuples renames the "_i" column
    for _, s in lineup.dropna(subset=["sleeper_id"]).iterrows():
        for _, b in bench.iterrows():
            if (
                b["position"] in SLOT_ELIGIBLE.get(s["slot"], {s["slot"]})
                and abs(s["proj"] - b["proj"]) <= CLOSE_CALL_POINTS
            ):
                row = {
                    "slot": s["slot"],
                    "start": s["name"],
                    "start_proj": s["proj"],
                    "bench": b["name"],
                    "bench_proj": b["proj"],
                    "gap": round(s["proj"] - b["proj"], 2),
                }
                if draws is not None and theirs is not None and starters:
                    swapped = [i for i in starters if i != int(s["_i"])] + [int(b["_i"])]
                    row["win_as_is"] = round(win_probability(starters, theirs, draws), 3)
                    row["win_if_swapped"] = round(win_probability(swapped, theirs, draws), 3)
                rows.append(row)
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
    matchup: str | None = None,
    swaps: list[tuple[str, str, str]] | None = None,
) -> str:
    """Short text version of the matchup, lineup with ranges, close calls and waiver targets."""
    lines = [f"**{league_name} | {season} week {week}** (projected {lineup['proj'].sum():.1f})"]
    if matchup:
        lines.append(matchup)
    lines.append("```")
    for r in lineup.itertuples():
        flag = f"  [{r.flag}]" if isinstance(r.flag, str) and r.flag else ""
        name = r.name if isinstance(r.name, str) else "(empty)"
        rng = f"{r.p10:4.1f}-{r.p90:4.1f}" if pd.notna(getattr(r, "p10", None)) else ""
        lines.append(f"{r.slot:<10} {name:<22} {r.proj:5.1f}  {rng}{flag}")
    lines.append("```")
    if swaps:
        lines.append("**To raise win probability**")
        lines += [f"- {slot}: start {inn} over {out}" for slot, inn, out in swaps]
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
    players, notes, draws = build_player_table(season, week, scoring)
    players["_i"] = np.arange(len(players))
    for note in notes:
        print(f"Note: {note}")

    roster = players[players["sleeper_id"].isin(mine.get("players") or [])]
    lineup = optimal_lineup(roster, slots)
    bench = roster[~roster["sleeper_id"].isin(lineup["sleeper_id"])].sort_values("proj", ascending=False)

    # This week's opponent: their set starters, or their best-projection lineup if none are set
    opp_name, theirs = None, []
    names = {u["user_id"]: u.get("display_name") for u in users}
    owners = {r["roster_id"]: names.get(r.get("owner_id")) for r in rosters}
    ms = sleeper.matchups(league_id, week)
    me = next((m for m in ms if m["roster_id"] == mine["roster_id"]), None)
    opp = next(
        (m for m in ms if me and m["matchup_id"] == me["matchup_id"] and m["roster_id"] != me["roster_id"]),
        None,
    )
    if opp:
        opp_name = owners.get(opp["roster_id"]) or f"roster {opp['roster_id']}"
        ids = [p for p in (opp.get("starters") or []) if p and p != "0"]
        if not ids:
            opp_roster = players[players["sleeper_id"].isin(opp.get("players") or [])]
            ids = list(optimal_lineup(opp_roster, slots)["sleeper_id"].dropna())
        theirs = players.loc[players["sleeper_id"].isin(ids), "_i"].astype(int).tolist()

    mine_ids = lineup["_i"].dropna().astype(int).tolist()
    matchup = None
    best_lineup, swaps = lineup, []
    if opp_name:
        win = win_probability(mine_ids, theirs, draws)
        mt, ot = draws[mine_ids].sum(axis=0), draws[theirs].sum(axis=0)
        matchup = (
            f"vs {opp_name}: win probability {win:.0%} "
            f"(you {np.median(mt):.0f}, range {np.quantile(mt, 0.1):.0f}-{np.quantile(mt, 0.9):.0f}; "
            f"them {np.median(ot):.0f}, range {np.quantile(ot, 0.1):.0f}-{np.quantile(ot, 0.9):.0f})"
        )
        best_lineup, swaps, best_win = max_win_lineup(lineup, bench, theirs, draws, players)
        if swaps:
            matchup += f". Best win-probability lineup: {best_win:.0%}"
    calls = close_calls(lineup, bench, theirs if opp_name else None, draws if opp_name else None)
    waivers = waiver_targets(players, rostered, lineup)

    cols = [
        "name",
        "role_label",
        "sleeper_team",
        "opponent",
        "proj",
        "p10",
        "p90",
        "ours",
        "sleeper",
        "implied_points",
        "flag",
    ]
    pd.set_option("display.width", 200)
    if matchup:
        print(f"\n=== Matchup ===\n{matchup}")
        for slot, inn, out in swaps:
            print(f"  {slot}: start {inn} over {out}")
    print("\n=== Best lineup (by projection; p10-p90 is the 80% range) ===")
    print(lineup[["slot"] + cols].round(2).to_string(index=False))
    total = lineup["center"].sum() if "center" in lineup else lineup["proj"].sum()
    print(f"Expected total: {total:.1f}")  # sum of means; each proj shown is a median (0016)
    print("\n=== Bench ===")
    print(bench[cols].round(2).to_string(index=False))
    print("\n=== Close calls (within 2 points) ===")
    print(calls.to_string(index=False) if not calls.empty else "None: every start is clear.")
    print("\n=== Waiver targets ===")
    wcols = [
        "name",
        "role_label",
        "position",
        "sleeper_team",
        "opponent",
        "proj",
        "p10",
        "p90",
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
    if swaps:
        best_lineup.to_csv(out / "lineup_max_win.csv", index=False)
    bench.to_csv(out / "bench.csv", index=False)
    calls.to_csv(out / "close_calls.csv", index=False)
    waivers.to_csv(out / "waivers.csv", index=False)
    players.to_csv(out / "all_projections.csv", index=False)
    print(f"\nWrote {out}")

    if discord:
        from nfl_model import alerts

        alerts.send(
            discord_summary(
                lg.get("name") or league_id,
                season,
                week,
                lineup,
                calls,
                waivers,
                notes,
                matchup=matchup,
                swaps=swaps,
            )
        )
