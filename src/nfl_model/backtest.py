"""Walk-forward backtest.

1. Tune recency half-lives and shrinkage on 2012-2017, seasons Sleeper never sees,
   so test seasons play no part in choosing them.
2. For each test season 2019-2025: fit team volume models on earlier seasons,
   project, and blend with Sleeper using per-position weights picked on earlier
   seasons only (2018 onward, when Sleeper projections start).
3. Score on MAE, within-week rank correlation, and close start/sit calls.

    uv run nflm backtest
"""

import itertools
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nfl_model import config, data, questionable
from nfl_model.availability import Renorm, add_roster_rows, add_team_usual, centers, key_absence, renormalize
from nfl_model.features import Params, add_player_features, add_team_features, season_priors
from nfl_model.model import fit_volume_models, predict_volume, project
from nfl_model.roles import RoleParams, add_role_curves, apply_roles, assign_roles, shrink_to_roles
from nfl_model.scoring import fantasy_points
from nfl_model.significance import close_call_gap, mae_gap

TUNE_SEASONS = range(2012, 2018)
BLEND_START = 2018
TEST_SEASONS = range(2019, 2026)
# Wide on purpose: a best value on the edge of the grid means the grid was too narrow
GRID = {
    "hl_share": [1, 1.5, 2, 3, 4, 6, 8, 12],
    "hl_eff": [1, 2, 3, 4, 6, 8, 16, 32],
    "k_mult": [0.125, 0.25, 0.5, 1.0, 2.0],
}
HL_TEAM_GRID = [2, 4, 16, 32]  # plus the default 8 already in the main grid
BLEND_WEIGHTS = np.round(np.arange(0, 1.0001, 0.05), 2)
CLOSE_CALL_POINTS = 2.0
RELEVANT_POINTS = 5.0  # Sleeper projection floor for "would you start this player?" rows
# Starters in a 12-team league: top N per position each week by Sleeper projection
STARTABLE = {"QB": 12, "RB": 24, "WR": 36, "TE": 12}
# Roster status (game-day inactives) is complete from 2016. Renormalization strength is tuned
# on 2016-2018: never scored, so 2019-2025 stays a clean test.
RENORM_SEASONS = range(2016, 2019)
BETA_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
VARIANTS = {"lock": "expected_active_lock", "midweek": "expected_active_midweek"}
LIVE_VARIANT = "midweek"  # live projections know the injury report, not the inactive list
# Roles (decision 0014): tuned on RENORM_SEASONS. Ranking by depth chart tier first beat ranking by
# recent share alone (2016-2018 MAE 4.548 vs 4.564), so only the depth rule is searched here.
ROLE_HL_GRID = [4.0, 8.0, 16.0]
ROLE_K_GRID = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]


def prepare(pg: pd.DataFrame, scoring: dict[str, float] | None = None) -> pd.DataFrame:
    pg = pg.copy()
    pg["fantasy_points"] = fantasy_points(pg, scoring)
    pg["played"] = 1.0
    return pg


def build_features(
    pg: pd.DataFrame, tg: pd.DataFrame, params: Params, status: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Player features (with roster placeholder rows when status is given) and team features."""
    rows = add_roster_rows(pg, status) if status is not None else pg
    feats = add_player_features(rows, params, season_priors(pg))
    for flag in VARIANTS.values():
        if flag not in feats:
            feats[flag] = True
    if status is not None:
        feats = add_team_usual(feats, tg, params.hl_team)
    return feats, add_team_features(tg, params.hl_team, params.coach_k)


def season_volumes(
    tgf: pd.DataFrame, seasons: range | list[int], specs: dict[str, list[str]] | None = None
) -> dict[int, pd.DataFrame]:
    """Team volume predictions per season, each from models fit on earlier seasons only."""
    out = {}
    for season in seasons:
        train = tgf[(tgf["season"] < season) & (tgf["season"] > tgf["season"].min())]
        out[season] = predict_volume(fit_volume_models(train, specs), tgf[tgf["season"] == season], specs)
    return out


def project_rows(
    feats: pd.DataFrame,
    volumes: dict[int, pd.DataFrame],
    seasons: range | list[int],
    scoring: dict[str, float] | None = None,
    renorm: Renorm | None = None,
    flag: str = VARIANTS["lock"],
    center: dict[str, float] | None = None,
    with_absence: bool = True,
    roles: RoleParams | None = None,
    sat_out: bool = False,
) -> pd.DataFrame:
    """Projections for played player-games in `seasons`, optionally renormalizing shares
    by who was expected to play and pulling them toward team role curves. Adds key_absence
    (a fresh absence on the team). sat_out=True also keeps players expected to play (`flag`)
    who did not, scored 0 (decision 0017)."""
    if roles is not None:
        # Role curves need every team's earlier seasons, so work on all rows at once
        feats = renormalize(feats, flag, renorm, center) if renorm is not None else feats
        feats = apply_roles(feats, flag, roles)
        renorm = None
    out = []
    for season in seasons:
        rows = feats[feats["season"] == season]
        if renorm is not None:
            rows = renormalize(rows, flag, renorm, center)
        if with_absence:
            rows = rows.assign(key_absence=key_absence(rows, flag))
        keep = rows["played"] == 1
        if sat_out:
            keep |= rows[flag].astype(bool)
        rows = rows[(rows["prior_games"] >= 1) & keep]
        out.append(project(rows, volumes[season], scoring))
    proj = pd.concat(out, ignore_index=True)
    if sat_out:
        proj["fantasy_points"] = proj["fantasy_points"].where(proj["played"] == 1, 0.0)
    return proj


def run_projection(
    pg: pd.DataFrame,
    tg: pd.DataFrame,
    params: Params,
    seasons: range | list[int],
    scoring: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Projections for every player-game in `seasons`, each season's volume model
    fit on earlier seasons only. No availability adjustment (used for tuning)."""
    feats, tgf = build_features(pg, tg, params)
    out = []
    for season in seasons:
        rows = feats[(feats["season"] == season) & (feats["prior_games"] >= 1)]
        out.append(project(rows, season_volumes(tgf, [season])[season], scoring))
    return pd.concat(out, ignore_index=True)


def tune_renorm(
    feats: pd.DataFrame, volumes: dict[int, pd.DataFrame], flag: str
) -> tuple[Renorm, dict[str, float], pd.DataFrame]:
    """Renormalization strength per share type, by opportunity MAE on 2016-2018."""
    center = centers(feats, flag, RENORM_SEASONS)
    rows = []
    for bt, bc, ba in itertools.product(BETA_GRID, BETA_GRID, BETA_GRID):
        renorm = Renorm(beta_target=bt, beta_carry=bc, beta_att=ba)
        proj = project_rows(
            feats, volumes, RENORM_SEASONS, renorm=renorm, flag=flag, center=center, with_absence=False
        )
        rows.append(
            {**asdict(renorm), "opp_mae": _mae(proj["opp_points"], proj["fantasy_points"]), "n": len(proj)}
        )
    grid = pd.DataFrame(rows)
    best = grid.loc[grid["opp_mae"].idxmin()]
    renorm = Renorm(float(best["beta_target"]), float(best["beta_carry"]), float(best["beta_att"]))
    return renorm, center, grid


def _mae(a: pd.Series, b: pd.Series) -> float:
    return float(np.mean(np.abs(a - b)))


def tune(pg: pd.DataFrame, tg: pd.DataFrame) -> tuple[Params, pd.DataFrame]:
    rows = []
    for hs, he, k in itertools.product(GRID["hl_share"], GRID["hl_eff"], GRID["k_mult"]):
        params = Params(hl_share=hs, hl_eff=he, k_mult=k)
        proj = run_projection(pg, tg, params, TUNE_SEASONS)
        rows.append(
            {
                **asdict(params),
                "opp_mae": _mae(proj["opp_points"], proj["fantasy_points"]),
                "share_mae": _mae(proj["share_points"], proj["fantasy_points"]),
                "n": len(proj),
            }
        )
        print(f"  share hl={hs:>2} eff hl={he:>2} k={k}: opp MAE {rows[-1]['opp_mae']:.3f}")
    grid = pd.DataFrame(rows)
    best = grid.loc[grid["opp_mae"].idxmin()]
    params = Params(
        hl_share=float(best["hl_share"]), hl_eff=float(best["hl_eff"]), k_mult=float(best["k_mult"])
    )

    team_rows = []
    for ht in HL_TEAM_GRID:
        p = replace(params, hl_team=ht)
        proj = run_projection(pg, tg, p, TUNE_SEASONS)
        team_rows.append(
            {
                **asdict(p),
                "opp_mae": _mae(proj["opp_points"], proj["fantasy_points"]),
                "share_mae": _mae(proj["share_points"], proj["fantasy_points"]),
                "n": len(proj),
            }
        )
        print(f"  team hl={ht:>2}: opp MAE {team_rows[-1]['opp_mae']:.3f}")
    team_grid = pd.concat([pd.DataFrame(team_rows), grid.loc[[grid["opp_mae"].idxmin()]]], ignore_index=True)
    params = replace(params, hl_team=float(team_grid.loc[team_grid["opp_mae"].idxmin(), "hl_team"]))
    return params, pd.concat([grid, team_grid.iloc[:-1]], ignore_index=True)


def best_share_half_life(grid: pd.DataFrame) -> float:
    """The points-share baseline only depends on hl_share; take its own best."""
    return float(grid.groupby("hl_share")["share_mae"].min().idxmin())


def pick_blend_weight(train: pd.DataFrame, model_col: str, shift: bool = True) -> tuple[float, float]:
    """Weight on our model (rest on Sleeper) that minimizes MAE on earlier seasons, then a constant
    shift: the median miss at that weight, the MAE-optimal constant. Fantasy points are right-skewed,
    so the median sits below the mean (decision 0016, amending 0006). The weight is picked before
    the shift, so one constant per position never reorders players within it.
    shift=False gives the blend before 0016, with no shift."""
    maes = [
        _mae(w * train[model_col] + (1 - w) * train["sleeper_projected_points"], train["fantasy_points"])
        for w in BLEND_WEIGHTS
    ]
    w = float(BLEND_WEIGHTS[int(np.argmin(maes))])
    if not shift:
        return w, 0.0
    blend = w * train[model_col] + (1 - w) * train["sleeper_projected_points"]
    return w, round(float(np.median(train["fantasy_points"] - blend)), 3)


def close_call_counts(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Per position-week: pairs Sleeper projects within 2 points of each other (`pairs`),
    and how many of them the player `col` ranks higher actually scored more (`wins`)."""
    rows = []
    for (season, week, position), grp in df.groupby(["season", "week", "position"]):
        s = grp["sleeper_projected_points"].to_numpy()
        m = grp[col].to_numpy()
        a = grp["fantasy_points"].to_numpy()
        i, j = np.triu_indices(len(grp), k=1)
        close = (np.abs(s[i] - s[j]) <= CLOSE_CALL_POINTS) & (a[i] != a[j]) & (m[i] != m[j])
        i, j = i[close], j[close]
        rows.append((season, week, position, int(np.sum((m[i] > m[j]) == (a[i] > a[j]))), len(i)))
    return pd.DataFrame(rows, columns=["season", "week", "position", "wins", "pairs"])


def close_call_accuracy(df: pd.DataFrame, col: str) -> tuple[float, int]:
    """Share of close pairs (see `close_call_counts`) that `col` orders correctly."""
    counts = close_call_counts(df, col)
    wins, total = int(counts["wins"].sum()), int(counts["pairs"].sum())
    return (wins / total if total else float("nan")), total


def rank_corr(df: pd.DataFrame, col: str) -> float:
    """Mean Spearman correlation of `col` with actual points within position-week."""
    corrs = df.groupby(["season", "week", "position"]).apply(
        lambda g: g[col].rank().corr(g["fantasy_points"].rank()) if len(g) > 2 else np.nan,
        include_groups=False,
    )
    return float(corrs.mean())


def evaluate(proj: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per position and test season: blend weights picked on earlier seasons, then metrics."""
    df = proj.dropna(subset=["sleeper_projected_points"]).copy()
    df = df[df["season"] >= BLEND_START]
    results, scored = [], []
    for (position, season), test in df[df["season"].isin(TEST_SEASONS)].groupby(["position", "season"]):
        # The only level adjustment is the median shift picked with the weight (0016). A linear
        # fit (actual ~ a + b * projection) raised MAE: it moves toward the mean, not the median (0006).
        train = df[(df["position"] == position) & (df["season"] < season)]
        test = test.copy()
        sleeper = test["sleeper_projected_points"]
        w_opp, c_opp = pick_blend_weight(train, "opp_points")
        w_share, c_share = pick_blend_weight(train, "share_points")
        w_raw, _ = pick_blend_weight(train, "opp_points", shift=False)
        test["blend_points"] = w_opp * test["opp_points"] + (1 - w_opp) * sleeper + c_opp
        test["blend_share_points"] = w_share * test["share_points"] + (1 - w_share) * sleeper + c_share
        test["blend_unshifted_points"] = w_raw * test["opp_points"] + (1 - w_raw) * sleeper
        scored.append(test)
        results.append(
            {
                "position": position,
                "season": season,
                "n": len(test),
                "w_opp": w_opp,
                "shift_opp": c_opp,
                "w_share": w_share,
                "shift_share": c_share,
                "w_unshifted": w_raw,
            }
        )
    scored = pd.concat(scored, ignore_index=True)
    return pd.DataFrame(results), scored.assign(startable=startable(scored))


def startable(df: pd.DataFrame) -> pd.Series:
    """True for the top N players at each position each week by Sleeper projection (`STARTABLE`).
    Ranked among scored rows, so a player ruled out late is not in the ranking."""
    rank = df.groupby(["season", "week", "position"])["sleeper_projected_points"].rank(
        method="first", ascending=False
    )
    return rank <= df["position"].map(STARTABLE)


def row_sets(df: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """All rows, relevant rows (Sleeper >= 5) and startable rows. Close calls skip `all`."""
    return [
        ("all", df),
        ("relevant", df[df["sleeper_projected_points"] >= RELEVANT_POINTS]),
        ("startable", df[df["startable"]]),
    ]


MODELS = {
    "sleeper": "sleeper_projected_points",
    "points_share": "share_points",
    "opportunity": "opp_points",
    "blend_share": "blend_share_points",
    "blend_opportunity": "blend_points",
    "blend_unshifted": "blend_unshifted_points",  # the blend before decision 0016
}


def summarize(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for subset_name, subset in row_sets(scored):
        for position in ["ALL"] + config.POSITIONS:
            sub = subset if position == "ALL" else subset[subset["position"] == position]
            for name, col in MODELS.items():
                acc, pairs = close_call_accuracy(sub, col) if subset_name != "all" else (np.nan, 0)
                rows.append(
                    {
                        "rows": subset_name,
                        "position": position,
                        "model": name,
                        "n": len(sub),
                        "mae": _mae(sub[col], sub["fantasy_points"]),
                        "bias": float((sub[col] - sub["fantasy_points"]).mean()),
                        "rank_corr": rank_corr(sub, col),
                        "close_call_acc": acc,
                        "close_call_pairs": pairs,
                    }
                )
    return pd.DataFrame(rows)


# Pairs compared within each variant, then the live variant against the others on the same rows
COMPARISONS = [
    ("blend_opportunity", "sleeper"),
    ("opportunity", "sleeper"),
    ("blend_opportunity", "blend_share"),
    ("blend_opportunity", "blend_unshifted"),
]
VARIANT_MODELS = ["opportunity", "blend_opportunity"]


def _gaps(frame: pd.DataFrame, a: str, b: str, labels: dict) -> list[dict]:
    """MAE gap (every row set) and close-call gap (relevant and startable rows) of `a` vs `b`,
    for all positions and each position, plus the all-rows MAE gap per season."""
    rows = []
    for subset_name, subset in row_sets(frame):
        for position in ["ALL"] + config.POSITIONS:
            sub = subset if position == "ALL" else subset[subset["position"] == position]
            key = {**labels, "rows": subset_name, "position": position, "season": "all"}
            rows.append({**key, "metric": "mae", **mae_gap(sub, a, b)})
            if subset_name != "all":
                gap = close_call_gap(close_call_counts(sub, a), close_call_counts(sub, b))
                rows.append({**key, "metric": "close_call_acc", **gap})
    for season, sub in frame.groupby("season"):
        key = {**labels, "rows": "all", "position": "ALL", "season": str(season)}
        rows.append({**key, "metric": "mae", **mae_gap(sub, a, b)})
    return rows


def significance(scored: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Week-clustered bootstrap intervals on the gap between models (within each variant)
    and between the live variant and the others (same model, same rows)."""
    rows = []
    for variant, frame in scored.items():
        for a, b in COMPARISONS:
            rows += _gaps(frame, MODELS[a], MODELS[b], {"variant": variant, "a": a, "b": b})
    keys = ["game_id", "gsis_id", "season", "week", "position", "fantasy_points", "sleeper_projected_points"]
    keys.append("startable")
    cols = [MODELS[m] for m in VARIANT_MODELS]
    for other in [v for v in scored if v != LIVE_VARIANT]:
        both = scored[LIVE_VARIANT][keys + cols].merge(
            scored[other][["game_id", "gsis_id"] + cols], on=["game_id", "gsis_id"], suffixes=("_a", "_b")
        )
        for model in VARIANT_MODELS:
            labels = {"variant": f"{LIVE_VARIANT} vs {other}", "a": model, "b": model}
            rows += _gaps(both, f"{MODELS[model]}_a", f"{MODELS[model]}_b", labels)
    return pd.DataFrame(rows)


def questionable_pair_counts(df: pd.DataFrame, base: str, col: str) -> pd.DataFrame:
    """Start/sit pairs a Questionable player is in: same position and week, `base` projections
    within 2 points, exactly one of the two Questionable. `wins`: pairs where `col` ranks the
    higher scorer first."""
    rows = []
    for (season, week, _), grp in df.groupby(["season", "week", "position"]):
        b, m, a = grp[base].to_numpy(), grp[col].to_numpy(), grp["fantasy_points"].to_numpy()
        q = grp["injury_status"].eq("Questionable").to_numpy()
        i, j = np.triu_indices(len(grp), k=1)
        pick = (np.abs(b[i] - b[j]) <= CLOSE_CALL_POINTS) & (q[i] != q[j]) & (a[i] != a[j]) & (m[i] != m[j])
        i, j = i[pick], j[pick]
        rows.append((season, week, int(np.sum((m[i] > m[j]) == (a[i] > a[j]))), len(i)))
    return pd.DataFrame(rows, columns=["season", "week", "wins", "pairs"])


def evaluate_questionable(
    exp: pd.DataFrame, status: pd.DataFrame, weights: pd.DataFrame
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Fit P(play) and the production multiplier on 2016-2018, then score the adjustment on
    2019-2025 over every expected-to-play player, those who sat scored 0 (decision 0017).

    Sleeper's stored projections mostly vanish for players who sat (they were updated after
    inactives), so the blend here uses each player's Sleeper projection from his latest earlier
    week, for every row alike. Returns the table, scored rows and a results frame."""
    st = status.assign(regular=questionable.previous_played(status)).sort_values(["gsis_id", "kickoff_utc"])
    st["sleeper_lag"] = st.groupby("gsis_id")["sleeper_projected_points"].transform(
        lambda x: x.shift(1).ffill()
    )
    cols = ["game_id", "gsis_id", "injury_status", "practice_status", "regular", "sleeper_lag"]
    df = exp.merge(st[cols], on=["game_id", "gsis_id"], how="left")
    df["regular"] = df["regular"].fillna(False).astype(bool)
    table = questionable.fit(df[df["season"].isin(questionable.FIT_SEASONS)])

    test = df[df["season"].isin(TEST_SEASONS)].copy()
    play, mult = questionable.factors(test, table)
    test["q_factor"] = play * mult
    test["opp_q_points"] = test["opp_points"] * test["q_factor"]
    w = weights[weights["variant"] == LIVE_VARIANT].set_index(["position", "season"])
    key = list(zip(test["position"], test["season"]))
    wt, shift = w.loc[key, "w_opp"].to_numpy(), w.loc[key, "shift_opp"].to_numpy()
    test["blend_lag_points"] = wt * test["opp_points"] + (1 - wt) * test["sleeper_lag"] + shift
    test["blend_lag_q_points"] = test["blend_lag_points"] * test["q_factor"]

    results = []
    for name, base, adj in [
        ("opportunity", "opp_points", "opp_q_points"),
        ("blend", "blend_lag_points", "blend_lag_q_points"),
    ]:
        rows = test.dropna(subset=[base])
        for subset, sub in [
            ("expected", rows),
            ("expected, projected >= 5", rows[rows[base] >= RELEVANT_POINTS]),
            ("questionable", rows[rows["injury_status"].eq("Questionable")]),
        ]:
            gap = mae_gap(sub, adj, base)
            results.append(
                {
                    "model": name,
                    "rows": subset,
                    "metric": "mae",
                    "base": _mae(sub[base], sub["fantasy_points"]),
                    **gap,
                }
            )
        cc = close_call_gap(
            questionable_pair_counts(rows, base, adj), questionable_pair_counts(rows, base, base)
        )
        results.append({"model": name, "rows": "pairs with one Questionable", "metric": "pair_acc", **cc})
    return table, test, pd.DataFrame(results)


def blend_weights(proj: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-position blend weight and median shift fit on every season with Sleeper projections
    (2018 onward)."""
    df = proj.dropna(subset=["sleeper_projected_points"])
    df = df[df["season"] >= BLEND_START]
    out = {}
    for position, rows in df.groupby("position"):
        w, c = pick_blend_weight(rows, "opp_points")
        out[position] = {"w": w, "shift": c}
    return out


def tune_roles(
    feats: pd.DataFrame, volumes: dict[int, pd.DataFrame], flag: str, renorm: Renorm, center: dict
) -> tuple[RoleParams, pd.DataFrame]:
    """Role curve half-life and pull strength (targets first, then carries), by opportunity MAE
    on 2016-2018, after availability renormalization."""
    base = renormalize(feats, flag, renorm, center)

    def score(f: pd.DataFrame) -> float:
        proj = project_rows(f, volumes, RENORM_SEASONS, with_absence=False)
        return _mae(proj["opp_points"], proj["fantasy_points"])

    rows = []
    for hl in ROLE_HL_GRID:
        curves = add_role_curves(base, assign_roles(base, flag, "depth"), hl)
        k_t = min(ROLE_K_GRID, key=lambda k: score(shrink_to_roles(curves, RoleParams("depth", hl, k, 0.0))))
        for k_c in ROLE_K_GRID:
            p = RoleParams("depth", hl, k_t, k_c)
            rows.append({**asdict(p), "opp_mae": score(shrink_to_roles(curves, p))})
    grid = pd.DataFrame(rows)
    best = grid.loc[grid["opp_mae"].idxmin()]
    return RoleParams("depth", float(best["hl_role"]), float(best["k_target"]), float(best["k_carry"])), grid


def model_card(params: Params, variants: dict[str, dict], questionable_table: dict | None = None) -> dict:
    """What live projections need: tuned params, the live variant's renormalization
    and blend weights, and the other variants for reference."""
    live = variants[LIVE_VARIANT]
    return {
        "params": asdict(params),
        "live_variant": LIVE_VARIANT,
        "renorm": live["renorm"],
        "center": live["center"],
        "roles": live["roles"],
        "positions": live["positions"],
        "variants": variants,
        **({"questionable": questionable_table} if questionable_table else {}),
    }


# Written by `nflm sim-backtest` into the same card; a backtest must not drop them
SIM_KEYS = ("sim", "sim_tails", "range_mix", "residual_table")


def keep_sim_keys(card: dict, previous: dict) -> tuple[dict, bool]:
    """`card` plus the range settings from the previous card, and whether they are now stale
    (the rest of the card changed, so the ranges were tuned on different projections)."""
    kept = {k: previous[k] for k in SIM_KEYS if k in previous}
    stale = bool(kept) and any(previous.get(k) != v for k, v in card.items())
    return {**card, **kept}, stale


def latest_run_dir() -> Path | None:
    runs = sorted((config.OUTPUT_DIR / "backtests").glob("*/model_card.json"))
    return runs[-1].parent if runs else None


def main(refresh: bool = False, skip_tune: bool = False) -> None:
    print("Loading data...")
    pg = prepare(data.load_player_games(refresh))
    tg = data.load_team_games(refresh)

    previous = sorted((config.OUTPUT_DIR / "backtests").glob("*/tuning_grid.csv"))
    if skip_tune and previous:
        grid = pd.read_csv(previous[-1])
        saved = json.loads((previous[-1].parent / "params.json").read_text())
        params = Params(**{k: saved[k] for k in ("hl_share", "hl_eff", "hl_team", "k_mult")})
        print(f"Reusing tuned params from {previous[-1].parent.name}")
    else:
        print(f"Tuning half-lives and shrinkage on {TUNE_SEASONS.start}-{TUNE_SEASONS.stop - 1}...")
        params, grid = tune(pg, tg)
    hl_share_baseline = best_share_half_life(grid)
    print(f"Best: {params}; points-share half-life {hl_share_baseline}")

    seasons = range(BLEND_START, TEST_SEASONS.stop)
    print("Building features with roster availability...")
    status = data.load_player_status(refresh)
    feats, tgf = build_features(pg, tg, params, status)
    volumes = season_volumes(tgf, range(RENORM_SEASONS.start, TEST_SEASONS.stop))
    share = run_projection(pg, tg, replace(params, hl_share=hl_share_baseline), seasons)
    share_points = share.set_index(["game_id", "gsis_id"])["share_points"]

    projections = {"none": project_rows(feats, volumes, seasons)}
    renorm_grids, role_grids, variants = [], [], {}
    for name, flag in VARIANTS.items():
        print(f"Tuning renormalization ({name}) on {RENORM_SEASONS.start}-{RENORM_SEASONS.stop - 1}...")
        renorm, center, rgrid = tune_renorm(feats, volumes, flag)
        renorm_grids.append(rgrid.assign(variant=name))
        print(f"  best {renorm}")
        print(f"Tuning roles ({name}) on {RENORM_SEASONS.start}-{RENORM_SEASONS.stop - 1}...")
        roles, role_grid = tune_roles(feats, volumes, flag, renorm, center)
        role_grids.append(role_grid.assign(variant=name))
        print(f"  best {roles}")
        projections[name] = project_rows(
            feats, volumes, seasons, renorm=renorm, flag=flag, center=center, roles=roles
        )
        variants[name] = {"renorm": asdict(renorm), "center": center, "roles": asdict(roles)}
        if name == LIVE_VARIANT:
            # Every expected-to-play player, those who sat scored 0, from 2016 for the Questionable fit
            expected = project_rows(
                feats,
                volumes,
                range(RENORM_SEASONS.start, TEST_SEASONS.stop),
                renorm=renorm,
                flag=flag,
                center=center,
                roles=roles,
                with_absence=False,
                sat_out=True,
            )

    summaries, absence, weights_all, by_season_all, scored_all = [], [], [], [], {}
    for name, proj in projections.items():
        proj["share_points"] = share_points.loc[list(zip(proj["game_id"], proj["gsis_id"]))].to_numpy()
        weights, scored = evaluate(proj)
        scored_all[name] = scored
        summaries.append(summarize(scored).assign(variant=name))
        absence.append(summarize(scored[scored["key_absence"]]).assign(variant=name))
        weights_all.append(weights.assign(variant=name))
        by_season_all.append(
            scored.groupby("season")
            .apply(
                lambda g: pd.Series({m: _mae(g[c], g["fantasy_points"]) for m, c in MODELS.items()}),
                include_groups=False,
            )
            .assign(variant=name)
        )
        if name in variants:
            variants[name]["positions"] = blend_weights(proj)
    summary = pd.concat(summaries, ignore_index=True)
    absence_summary = pd.concat(absence, ignore_index=True)
    weights = pd.concat(weights_all, ignore_index=True)
    by_season = pd.concat(by_season_all)
    print("Fitting Questionable players on 2016-2018, scoring expected players who sat...")
    q_table, q_scored, q_results = evaluate_questionable(expected, status, weights)
    print(f"  {q_table}")
    print("Bootstrapping intervals by week...")
    sig = significance(scored_all)

    out_dir = config.OUTPUT_DIR / "backtests" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(out_dir / "tuning_grid.csv", index=False)
    pd.concat(renorm_grids).to_csv(out_dir / "renorm_grid.csv", index=False)
    pd.concat(role_grids).to_csv(out_dir / "role_grid.csv", index=False)
    weights.to_csv(out_dir / "blend_weights.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)
    absence_summary.to_csv(out_dir / "summary_key_absence.csv", index=False)
    by_season.to_csv(out_dir / "mae_by_season.csv")
    sig.to_csv(out_dir / "significance.csv", index=False)
    # Every scored player-game of the live variant, for analyses of where the blend misses
    scored_all[LIVE_VARIANT].to_parquet(out_dir / "scored.parquet", index=False)
    q_results.to_csv(out_dir / "questionable.csv", index=False)
    q_scored.to_parquet(out_dir / "scored_expected.parquet", index=False)
    (out_dir / "params.json").write_text(
        json.dumps({**asdict(params), "hl_share_points_share": hl_share_baseline}, indent=2)
    )
    previous = json.loads(config.MODEL_CARD.read_text()) if config.MODEL_CARD.exists() else {}
    full, sim_stale = keep_sim_keys(model_card(params, variants, q_table), previous)
    card = json.dumps(full, indent=2)
    (out_dir / "model_card.json").write_text(card)
    config.MODEL_CARD.parent.mkdir(exist_ok=True)
    config.MODEL_CARD.write_text(card + "\n")

    pd.set_option("display.width", 180)
    cols = ["variant", "model", "n", "mae", "bias", "rank_corr", "close_call_acc"]
    pick = summary["model"].isin(["sleeper", "opportunity", "blend_unshifted", "blend_opportunity"])
    print("\n=== All rows, ALL positions, 2019-2025 ===")
    print(
        summary[pick & (summary["rows"] == "all") & (summary["position"] == "ALL")][cols]
        .round(4)
        .to_string(index=False)
    )
    print("\n=== Relevant rows (Sleeper >= 5), ALL positions ===")
    print(
        summary[pick & (summary["rows"] == "relevant") & (summary["position"] == "ALL")][cols]
        .round(4)
        .to_string(index=False)
    )
    print("\n=== Startable rows (weekly top 12 QB, 24 RB, 36 WR, 12 TE by Sleeper), ALL positions ===")
    print(
        summary[pick & (summary["rows"] == "startable") & (summary["position"] == "ALL")][cols]
        .round(4)
        .to_string(index=False)
    )
    a_pick = absence_summary["model"].isin(["sleeper", "opportunity", "blend_unshifted", "blend_opportunity"])
    print("\n=== Players on teams with a fresh key absence, relevant rows ===")
    print(
        absence_summary[a_pick & (absence_summary["rows"] == "relevant")][["position"] + cols]
        .round(4)
        .to_string(index=False)
    )
    print("\n=== MAE by season (blend_opportunity) ===")
    print(
        by_season.pivot_table(index="season", columns="variant", values="blend_opportunity")
        .join(by_season[by_season["variant"] == "none"]["sleeper"])
        .round(3)
        .to_string()
    )
    sig_cols = ["variant", "a", "b", "rows", "metric", "estimate", "lo", "hi", "p"]
    headline = (sig["position"] == "ALL") & (sig["season"] == "all")
    headline &= sig["variant"].str.startswith(LIVE_VARIANT)
    print(
        "\n=== Gap a - b with 95% week-bootstrap interval (MAE: negative favors a; close calls: positive) ==="
    )
    print(sig[headline][sig_cols].round(4).to_string(index=False))
    print("\n=== Questionable adjustment, 2019-2025, every expected player (sat out = 0) ===")
    print(
        "(MAE: adjusted minus unadjusted, negative favors the adjustment; pairs: accuracy gap, positive favors it)"
    )
    print(
        q_results[["model", "rows", "metric", "n", "estimate", "lo", "hi", "p"]]
        .round(4)
        .to_string(index=False)
    )
    print(f"\nWrote {out_dir} and {config.MODEL_CARD.relative_to(config.ROOT)} (commit it to deploy)")
    if sim_stale:
        print(
            "The model changed: range settings were kept from the old card. Run `nflm sim-backtest` before committing."
        )
