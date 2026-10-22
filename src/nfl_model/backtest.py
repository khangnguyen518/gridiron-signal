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

from nfl_model import config, data
from nfl_model.availability import Renorm, add_roster_rows, add_team_usual, centers, key_absence, renormalize
from nfl_model.features import Params, add_player_features, add_team_features, season_priors
from nfl_model.model import fit_volume_models, predict_volume, project
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
# Roster status (game-day inactives) is complete from 2016. Renormalization strength is tuned
# on 2016-2018: never scored, so 2019-2025 stays a clean test.
RENORM_SEASONS = range(2016, 2019)
BETA_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
VARIANTS = {"lock": "expected_active_lock", "midweek": "expected_active_midweek"}
LIVE_VARIANT = "midweek"  # live projections know the injury report, not the inactive list


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
) -> pd.DataFrame:
    """Projections for played player-games in `seasons`, optionally renormalizing shares
    by who was expected to play. Adds key_absence (a fresh absence on the team)."""
    out = []
    for season in seasons:
        rows = feats[feats["season"] == season]
        if renorm is not None:
            rows = renormalize(rows, flag, renorm, center)
        if with_absence:
            rows = rows.assign(key_absence=key_absence(rows, flag))
        rows = rows[(rows["prior_games"] >= 1) & (rows["played"] == 1)]
        out.append(project(rows, volumes[season], scoring))
    return pd.concat(out, ignore_index=True)


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


def pick_blend_weight(train: pd.DataFrame, model_col: str) -> float:
    """Weight on our model (rest on Sleeper) that minimizes MAE on earlier seasons."""
    maes = [
        _mae(w * train[model_col] + (1 - w) * train["sleeper_projected_points"], train["fantasy_points"])
        for w in BLEND_WEIGHTS
    ]
    return float(BLEND_WEIGHTS[int(np.argmin(maes))])


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
        # No level calibration: tried a linear fit (actual ~ a + b * projection) and it raised
        # MAE, because it moves projections toward the mean of right-skewed points, not the median.
        train = df[(df["position"] == position) & (df["season"] < season)]
        test = test.copy()
        w_opp = pick_blend_weight(train, "opp_points")
        w_share = pick_blend_weight(train, "share_points")
        test["blend_points"] = w_opp * test["opp_points"] + (1 - w_opp) * test["sleeper_projected_points"]
        test["blend_share_points"] = (
            w_share * test["share_points"] + (1 - w_share) * test["sleeper_projected_points"]
        )
        scored.append(test)
        results.append(
            {"position": position, "season": season, "n": len(test), "w_opp": w_opp, "w_share": w_share}
        )
    return pd.DataFrame(results), pd.concat(scored, ignore_index=True)


MODELS = {
    "sleeper": "sleeper_projected_points",
    "points_share": "share_points",
    "opportunity": "opp_points",
    "blend_share": "blend_share_points",
    "blend_opportunity": "blend_points",
}


def summarize(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for subset_name, subset in [
        ("all", scored),
        ("relevant", scored[scored["sleeper_projected_points"] >= RELEVANT_POINTS]),
    ]:
        for position in ["ALL"] + config.POSITIONS:
            sub = subset if position == "ALL" else subset[subset["position"] == position]
            for name, col in MODELS.items():
                acc, pairs = close_call_accuracy(sub, col) if subset_name == "relevant" else (np.nan, 0)
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
]
VARIANT_MODELS = ["opportunity", "blend_opportunity"]


def _gaps(frame: pd.DataFrame, a: str, b: str, labels: dict) -> list[dict]:
    """MAE gap (all and relevant rows) and close-call gap (relevant rows) of `a` vs `b`,
    for all positions and each position, plus the all-rows MAE gap per season."""
    rows = []
    for subset_name, subset in [
        ("all", frame),
        ("relevant", frame[frame["sleeper_projected_points"] >= RELEVANT_POINTS]),
    ]:
        for position in ["ALL"] + config.POSITIONS:
            sub = subset if position == "ALL" else subset[subset["position"] == position]
            key = {**labels, "rows": subset_name, "position": position, "season": "all"}
            rows.append({**key, "metric": "mae", **mae_gap(sub, a, b)})
            if subset_name == "relevant":
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
    cols = [MODELS[m] for m in VARIANT_MODELS]
    for other in [v for v in scored if v != LIVE_VARIANT]:
        both = scored[LIVE_VARIANT][keys + cols].merge(
            scored[other][["game_id", "gsis_id"] + cols], on=["game_id", "gsis_id"], suffixes=("_a", "_b")
        )
        for model in VARIANT_MODELS:
            labels = {"variant": f"{LIVE_VARIANT} vs {other}", "a": model, "b": model}
            rows += _gaps(both, f"{MODELS[model]}_a", f"{MODELS[model]}_b", labels)
    return pd.DataFrame(rows)


def blend_weights(proj: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-position blend weight fit on every season with Sleeper projections (2018 onward)."""
    df = proj.dropna(subset=["sleeper_projected_points"])
    df = df[df["season"] >= BLEND_START]
    return {
        position: {"w": pick_blend_weight(rows, "opp_points")} for position, rows in df.groupby("position")
    }


def model_card(params: Params, variants: dict[str, dict]) -> dict:
    """What live projections need: tuned params, the live variant's renormalization
    and blend weights, and the other variants for reference."""
    live = variants[LIVE_VARIANT]
    return {
        "params": asdict(params),
        "live_variant": LIVE_VARIANT,
        "renorm": live["renorm"],
        "center": live["center"],
        "positions": live["positions"],
        "variants": variants,
    }


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
    renorm_grids, variants = [], {}
    for name, flag in VARIANTS.items():
        print(f"Tuning renormalization ({name}) on {RENORM_SEASONS.start}-{RENORM_SEASONS.stop - 1}...")
        renorm, center, rgrid = tune_renorm(feats, volumes, flag)
        renorm_grids.append(rgrid.assign(variant=name))
        projections[name] = project_rows(feats, volumes, seasons, renorm=renorm, flag=flag, center=center)
        variants[name] = {"renorm": asdict(renorm), "center": center}
        print(f"  best {renorm}")

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
    print("Bootstrapping intervals by week...")
    sig = significance(scored_all)

    out_dir = config.OUTPUT_DIR / "backtests" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(out_dir / "tuning_grid.csv", index=False)
    pd.concat(renorm_grids).to_csv(out_dir / "renorm_grid.csv", index=False)
    weights.to_csv(out_dir / "blend_weights.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)
    absence_summary.to_csv(out_dir / "summary_key_absence.csv", index=False)
    by_season.to_csv(out_dir / "mae_by_season.csv")
    sig.to_csv(out_dir / "significance.csv", index=False)
    (out_dir / "params.json").write_text(
        json.dumps({**asdict(params), "hl_share_points_share": hl_share_baseline}, indent=2)
    )
    card = json.dumps(model_card(params, variants), indent=2)
    (out_dir / "model_card.json").write_text(card)
    config.MODEL_CARD.parent.mkdir(exist_ok=True)
    config.MODEL_CARD.write_text(card + "\n")

    pd.set_option("display.width", 180)
    cols = ["variant", "model", "n", "mae", "bias", "rank_corr", "close_call_acc"]
    pick = summary["model"].isin(["sleeper", "opportunity", "blend_opportunity"])
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
    a_pick = absence_summary["model"].isin(["sleeper", "opportunity", "blend_opportunity"])
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
    print(f"\nWrote {out_dir} and {config.MODEL_CARD.relative_to(config.ROOT)} (commit it to deploy)")
