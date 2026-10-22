"""Calibrate and test the game simulation's ranges.

    uv run nflm sim-backtest

1. Project 2012-2025 with the live model (availability renormalization, midweek).
2. Fit game-script slopes (pass and rush attempts vs margin deviation) on 2012-2017.
3. Tune kappa, eta and yards noise on 2016-2018 by pinball loss, averaged over the
   10th, 25th, 50th, 75th and 90th percentiles. Seasons 2019-2025 play no part.
4. Test 2019-2025: interval coverage (10-90 should hold 80% of outcomes, 25-75 should
   hold 50%), pinball loss, against a baseline that adds historical residual quantiles
   (by position and projection level) to the projection. Also check that a QB and his
   top receiver are correlated in the simulation about as much as in real games.
5. Write the chosen settings into model/model_card.json under "sim".
"""

import itertools
import json
from dataclasses import replace
from datetime import datetime

import numpy as np
import pandas as pd

from nfl_model import config, data
from nfl_model.availability import Renorm
from nfl_model.backtest import (
    VARIANTS,
    build_features,
    evaluate,
    prepare,
    project_rows,
    season_volumes,
)
from nfl_model.features import Params
from nfl_model.simulate import (
    QUANTILES,
    SimParams,
    fit_script,
    mix_with_residuals,
    quantile_frame,
    rescale,
    residual_table,
    simulate,
    stretch_tails,
)

SCRIPT_SEASONS = range(2012, 2018)
CALIBRATE_SEASONS = range(2016, 2019)
TEST_SEASONS = range(2019, 2026)
GRID = {"kappa": [15.0, 30.0, 60.0, 120.0], "eta": [0.0, 0.5, 1.0], "yds_sd_mult": [0.75, 1.0, 1.25]}
TAIL_GRID = [0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6]
MIX_SEASONS = range(2017, 2019)  # the baseline needs a season of history (2016) first
MIX_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
N_TUNE, N_TEST = 400, 1000
QCOLS = [f"p{round(q * 100):02d}" for q in QUANTILES]


def pinball(actual: np.ndarray, pred: pd.DataFrame) -> float:
    losses = []
    for q, c in zip(QUANTILES, QCOLS):
        d = actual - pred[c].to_numpy()
        losses.append(np.mean(np.maximum(q * d, (q - 1) * d)))
    return float(np.mean(losses))


def coverage(actual: np.ndarray, pred: pd.DataFrame) -> dict[str, float]:
    return {
        "cover_10_90": float(np.mean((actual >= pred["p10"]) & (actual <= pred["p90"]))),
        "cover_25_75": float(np.mean((actual >= pred["p25"]) & (actual <= pred["p75"]))),
        "below_p10": float(np.mean(actual < pred["p10"])),
        "above_p90": float(np.mean(actual > pred["p90"])),
    }


def sim_quantiles(
    proj: pd.DataFrame,
    seasons,
    params: SimParams,
    n: int,
    center: str = "opp_points",
    tails: dict[str, list[float]] | None = None,
    mix: dict[str, float] | None = None,
    table: dict | None = None,
):
    """Quantiles per row, one simulation per week so draws share game randomness. With mix and
    table, draws go through the same transform as live projections (mix_with_residuals)."""
    out = []
    for (season, week), rows in proj[proj["season"].isin(seasons)].groupby(["season", "week"]):
        c = rows[center].to_numpy()
        pos = rows["position"].to_numpy()
        draws = rescale(simulate(rows, params, n=n, seed=season * 100 + week), c)
        draws = stretch_tails(draws, c, pos, tails)
        draws = mix_with_residuals(draws, c, pos, table, mix)
        q = quantile_frame(draws)
        q.index = rows.index
        out.append(q)
    return pd.concat(out).loc[proj[proj["season"].isin(seasons)].index]


def tune_tails(q: pd.DataFrame, rows: pd.DataFrame, center: str = "opp_points") -> dict[str, list[float]]:
    """Per position, the downside and upside stretch with the lowest pinball loss. Quantiles
    transform exactly (the stretch is monotone), so no new simulation is needed."""
    tails = {}
    c = rows[center].to_numpy()[:, None]
    qv = q[QCOLS].to_numpy()
    for pos in config.POSITIONS:
        m = (rows["position"] == pos).to_numpy()
        actual = rows["fantasy_points"].to_numpy()[m]
        best = (np.inf, 1.0, 1.0)
        for lo, hi in itertools.product(TAIL_GRID, TAIL_GRID):
            dev = qv[m] - c[m]
            stretched = pd.DataFrame(c[m] + np.where(dev < 0, lo, hi) * dev, columns=QCOLS)
            loss = pinball(actual, stretched)
            if loss < best[0]:
                best = (loss, lo, hi)
        tails[pos] = [best[1], best[2]]
    return tails


def tune_mix(sim_q: pd.DataFrame, base_q: pd.DataFrame, rows: pd.DataFrame) -> dict[str, float]:
    """Per position, the weight on the simulation's quantiles (rest on the residual baseline's)
    with the lowest pinball loss. Mixing the draws' ranks mixes the quantiles exactly."""
    weights = {}
    for pos in config.POSITIONS:
        m = (rows["position"] == pos).to_numpy()
        y = rows["fantasy_points"].to_numpy()[m]
        losses = [pinball(y, w * sim_q[QCOLS][m] + (1 - w) * base_q[QCOLS][m]) for w in MIX_GRID]
        weights[pos] = MIX_GRID[int(np.argmin(losses))]
    return weights


def baseline_quantiles(proj: pd.DataFrame, season: int, center: str = "opp_points") -> pd.DataFrame:
    """Projection plus residual quantiles by position and projection quintile, from 2016 to season-1."""
    train = proj[(proj["season"] >= CALIBRATE_SEASONS.start) & (proj["season"] < season)].copy()
    test = proj[proj["season"] == season].copy()
    edges = np.quantile(train[center], [0.2, 0.4, 0.6, 0.8])
    train["bin"], test["bin"] = np.digitize(train[center], edges), np.digitize(test[center], edges)
    train["resid"] = train["fantasy_points"] - train[center]
    rq = train.groupby(["position", "bin"])["resid"].quantile(list(QUANTILES)).unstack()
    rq.columns = QCOLS
    q = test[["position", "bin"]].join(rq, on=["position", "bin"])[QCOLS]
    return q.add(test[center], axis=0).clip(lower=0)


def qb_receiver_corr(
    proj: pd.DataFrame, params: SimParams, seasons, n: int, tails=None, mix=None, table=None
) -> tuple[float, float]:
    """Correlation between a team's QB and its top-target receiver: in the simulation after the
    live transforms (average over team-games) and in actual results (residuals from the projection)."""
    sim_c, pairs = [], []
    for (season, week), rows in proj[proj["season"].isin(seasons)].groupby(["season", "week"]):
        c, pos = rows["opp_points"].to_numpy(), rows["position"].to_numpy()
        draws = rescale(simulate(rows, params, n=n, seed=season * 100 + week), c)
        draws = mix_with_residuals(stretch_tails(draws, c, pos, tails), c, pos, table, mix)
        rows = rows.assign(_i=np.arange(len(rows)))
        for _, tg in rows.groupby(["game_id", "team"]):
            qb = tg[tg["position"] == "QB"].sort_values("att_share").tail(1)
            rec = tg[tg["position"] != "QB"].sort_values("target_share").tail(1)
            if qb.empty or rec.empty:
                continue
            i, j = qb["_i"].item(), rec["_i"].item()
            sim_c.append(np.corrcoef(draws[i], draws[j])[0, 1])
            pairs.append(
                (
                    qb["fantasy_points"].item() - qb["opp_points"].item(),
                    rec["fantasy_points"].item() - rec["opp_points"].item(),
                )
            )
    actual = np.corrcoef(np.array(pairs).T)[0, 1]
    return float(np.nanmean(sim_c)), float(actual)


def main(refresh: bool = False) -> None:
    card = json.loads(config.MODEL_CARD.read_text())
    params = Params(**card["params"])
    print("Projecting 2012-2025 with the live model...")
    pg = prepare(data.load_player_games(refresh))
    tg = data.load_team_games(refresh)
    feats, tgf = build_features(pg, tg, params, data.load_player_status(refresh))
    volumes = season_volumes(tgf, range(SCRIPT_SEASONS.start, TEST_SEASONS.stop))
    proj = project_rows(
        feats,
        volumes,
        range(SCRIPT_SEASONS.start, TEST_SEASONS.stop),
        renorm=Renorm(**card["renorm"]),
        flag=VARIANTS[card["live_variant"]],
        center=card["center"],
        with_absence=False,
    )
    proj = proj.dropna(subset=["opp_points", "implied_points", "team_pass_attempts_hat"]).reset_index(
        drop=True
    )

    # Game script, from team-games with volume predictions
    vol = pd.concat(volumes.values())
    opp = tg[["game_id", "team", "points_scored"]].rename(
        columns={"team": "opponent", "points_scored": "opp_pts"}
    )
    teams = tg.merge(vol, on=["game_id", "team"]).merge(opp, on=["game_id", "opponent"])
    teams["margin"] = teams["points_scored"] - teams["opp_pts"]
    script_pass, script_rush = fit_script(teams[teams["season"].isin(SCRIPT_SEASONS)])
    base = SimParams(script_pass=script_pass, script_rush=script_rush)
    print(f"Game script: pass {script_pass:.3f}, rush {script_rush:.3f} log-attempts per 7 points of margin")

    print(f"Tuning on {CALIBRATE_SEASONS.start}-{CALIBRATE_SEASONS.stop - 1}...")
    cal = proj[proj["season"].isin(CALIBRATE_SEASONS)]
    rows = []
    for kappa, eta, sd in itertools.product(GRID["kappa"], GRID["eta"], GRID["yds_sd_mult"]):
        p = replace(base, kappa=kappa, eta=eta, yds_sd_mult=sd)
        q = sim_quantiles(proj, CALIBRATE_SEASONS, p, N_TUNE)
        rows.append(
            {
                "kappa": kappa,
                "eta": eta,
                "yds_sd_mult": sd,
                "pinball": pinball(cal["fantasy_points"].to_numpy(), q),
                **coverage(cal["fantasy_points"].to_numpy(), q),
            }
        )
        print(
            f"  kappa={kappa:>5} eta={eta} sd={sd}: pinball {rows[-1]['pinball']:.4f}, "
            f"10-90 cover {rows[-1]['cover_10_90']:.3f}"
        )
    grid = pd.DataFrame(rows)
    best = grid.loc[grid["pinball"].idxmin()]
    sim = replace(
        base, kappa=float(best["kappa"]), eta=float(best["eta"]), yds_sd_mult=float(best["yds_sd_mult"])
    )
    print(f"Best: {sim}")
    tails = tune_tails(sim_quantiles(proj, CALIBRATE_SEASONS, sim, N_TUNE), cal)
    print(f"Tail stretch (downside, upside) by position: {tails}")
    mix_rows = proj[proj["season"].isin(MIX_SEASONS)]
    mix = tune_mix(
        sim_quantiles(proj, MIX_SEASONS, sim, N_TUNE, tails=tails),
        pd.concat([baseline_quantiles(proj, s) for s in MIX_SEASONS]).loc[mix_rows.index],
        mix_rows,
    )
    print(f"Weight on the simulation in each range (rest on history) by position: {mix}")

    print("Testing ranges on 2019-2025...")
    test = proj[proj["season"].isin(TEST_SEASONS)].copy()
    test["share_points"] = test["opp_points"]  # evaluate() needs it; only blend_points is used here
    _, scored = evaluate(test)
    raw_q = sim_quantiles(proj, TEST_SEASONS, sim, N_TEST)
    sim_q = sim_quantiles(proj, TEST_SEASONS, sim, N_TEST, tails=tails)
    base_q = pd.concat([baseline_quantiles(proj, s) for s in TEST_SEASONS]).loc[test.index]
    wpos = test["position"].map(mix).to_numpy()[:, None]
    mixed_q = pd.DataFrame(
        wpos * sim_q[QCOLS].to_numpy() + (1 - wpos) * base_q[QCOLS].to_numpy(),
        columns=QCOLS,
        index=test.index,
    )
    actual = test["fantasy_points"].to_numpy()

    results = []
    for name, q in [
        ("mixed (live)", mixed_q),
        ("simulation", sim_q),
        ("simulation, no tail stretch", raw_q),
        ("residual baseline", base_q),
    ]:
        results.append(
            {
                "ranges": name,
                "center": "ours",
                "rows": len(test),
                "pinball": pinball(actual, q),
                **coverage(actual, q),
            }
        )
        for pos in config.POSITIONS:
            m = (test["position"] == pos).to_numpy()
            results.append(
                {
                    "ranges": name,
                    "center": f"ours, {pos}",
                    "rows": int(m.sum()),
                    "pinball": pinball(actual[m], q[m]),
                    **coverage(actual[m], q[m]),
                }
            )

    # The same simulation shape around the blend (what the league tool shows)
    keyed = scored.set_index(["game_id", "gsis_id"])["blend_points"]
    has_blend = test.set_index(["game_id", "gsis_id"]).index.isin(keyed.index)
    tb = test[has_blend].copy()
    tb["blend_points"] = keyed.loc[list(zip(tb["game_id"], tb["gsis_id"]))].to_numpy()
    # Exactly the live transform, with a history table that ends before the test seasons
    table_pre = residual_table(proj[proj["season"].isin(CALIBRATE_SEASONS)])
    blend_q = sim_quantiles(
        tb, TEST_SEASONS, sim, N_TEST, center="blend_points", tails=tails, mix=mix, table=table_pre
    )
    results.append(
        {
            "ranges": "mixed (live transform)",
            "center": "blend (Sleeper rows)",
            "rows": len(tb),
            "pinball": pinball(tb["fantasy_points"].to_numpy(), blend_q),
            **coverage(tb["fantasy_points"].to_numpy(), blend_q),
        }
    )
    res = pd.DataFrame(results)

    sim_corr, actual_corr = qb_receiver_corr(proj, sim, range(2023, 2026), 400, tails, mix, table_pre)
    widths = (sim_q["p90"] - sim_q["p10"]).groupby(test["position"]).median()

    out_dir = config.OUTPUT_DIR / "sim_backtests" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(out_dir / "calibration_grid.csv", index=False)
    res.to_csv(out_dir / "ranges.csv", index=False)
    card["sim"] = sim.as_dict()
    card["sim_tails"] = tails
    card["range_mix"] = mix
    card["residual_table"] = residual_table(proj[proj["season"] >= CALIBRATE_SEASONS.start])
    config.MODEL_CARD.write_text(json.dumps(card, indent=2) + "\n")

    pd.set_option("display.width", 180)
    print("\n=== Calibration grid, best 8 (2016-2018) ===")
    print(grid.sort_values("pinball").head(8).round(4).to_string(index=False))
    print("\n=== Ranges, 2019-2025 (10-90 should cover 0.80, 25-75 should cover 0.50) ===")
    print(res.round(4).to_string(index=False))
    print(f"\nMedian 10-90 width by position: {widths.round(1).to_dict()}")
    print(f"QB and top receiver correlation, 2023-2025: simulation {sim_corr:.3f}, actual {actual_corr:.3f}")
    print(f"\nWrote {out_dir}; model/model_card.json now has 'sim' (commit it to deploy)")
