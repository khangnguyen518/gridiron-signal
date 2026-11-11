"""Walk-forward test of the kicker and defense stat-line models against Sleeper (decision 0021).

    uv run nflm kdef-backtest

For each season S in 2018-2025 the stat models fit on 2010 to S-1. Per position, a blend weight on
our projection (rest on Sleeper) and a median shift are picked on 2018 to S-1, as for skill players
(0016). Scored on 2019-2025 against Sleeper's league-scored actuals; the bar, set before building:
beat Sleeper on startable MAE (top 12 by Sleeper each week) with an interval excluding zero, and not
lose to the direct-points prototype (median regression of points on the lines) beyond noise.
Writes the fits for live projections into the model card under "kdef".
"""

import json
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import QuantileRegressor

from nfl_model import config, data, kdef
from nfl_model.backtest import BLEND_WEIGHTS
from nfl_model.scoring import DEFAULT_SCORING
from nfl_model.significance import close_call_gap, mae_gap

SEASONS = range(2018, 2026)
TEST = range(2019, 2026)
N_DRAWS = 400


def _cc_counts(df: pd.DataFrame, col: str) -> pd.DataFrame:
    rows = []
    for (season, week), g in df.groupby(["season", "week"]):
        s, m, a = g["sleeper"].to_numpy(), g[col].to_numpy(), g["fantasy_points"].to_numpy()
        i, j = np.triu_indices(len(g), k=1)
        close = (np.abs(s[i] - s[j]) <= 2) & (a[i] != a[j]) & (m[i] != m[j])
        i, j = i[close], j[close]
        rows.append((season, week, int(np.sum((m[i] > m[j]) == (a[i] > a[j]))), len(i)))
    return pd.DataFrame(rows, columns=["season", "week", "wins", "pairs"])


def pick_blend(train: pd.DataFrame) -> tuple[float, float]:
    """Weight on ours (rest on Sleeper) minimizing MAE, then the median miss at it (as 0016)."""
    maes = [
        np.mean(np.abs(w * train["ours"] + (1 - w) * train["sleeper"] - train["fantasy_points"]))
        for w in BLEND_WEIGHTS
    ]
    w = float(BLEND_WEIGHTS[int(np.argmin(maes))])
    shift = float(np.median(train["fantasy_points"] - (w * train["ours"] + (1 - w) * train["sleeper"])))
    return w, round(shift, 3)


def main() -> None:
    scoring = DEFAULT_SCORING
    tg = data.load_team_games()
    dg_rows = kdef.defense_rows(data.load_defense_games(), tg)
    kg = data.load_kicker_games()
    kg_rows = kdef.kicker_rows(kg, tg)
    sl = data.load_sleeper_kdef().rename(
        columns={"projected_points": "sleeper", "actual_points": "fantasy_points"}
    )
    sl = sl.dropna(subset=["sleeper", "fantasy_points"])

    # Team kicker slot -> the kicker who kicked most that game, for matching to Sleeper
    kg["kicks"] = kg[[c for c in kg if c.startswith("fga_")]].sum(axis=1) + kg["xpa"]
    main_k = kg.sort_values("kicks").drop_duplicates(["game_id", "team"], keep="last")[
        ["game_id", "team", "gsis_id"]
    ]

    # Range width: a stretch factor per position, calibrated on 2015-2017 against points rebuilt from
    # play-by-play (each season's models fit on earlier seasons), then held fixed for the test
    rng = np.random.default_rng(20261111)
    cal = {"DEF": ([], []), "K": ([], [])}
    for season in range(2015, 2018):
        d = dg_rows[(dg_rows["season"] == season) & dg_rows["opp_implied"].notna()]
        k = kg_rows[(kg_rows["season"] == season) & kg_rows["implied_points"].notna()]
        d_fit = kdef.fit_defense(dg_rows[dg_rows["season"] < season])
        k_fit = kdef.fit_kicker(kg_rows[kg_rows["season"] < season])
        cal["DEF"][0].append(kdef.draw_defense(d, d_fit, scoring, N_DRAWS, rng))
        cal["DEF"][1].append(kdef.actual_defense_points(d, scoring).to_numpy())
        cal["K"][0].append(kdef.draw_kicker(k, k_fit, scoring, N_DRAWS, rng))
        cal["K"][1].append(kdef.actual_kicker_points(k, scoring).to_numpy())
    factors = {
        pos: kdef.calibrate_stretch(np.vstack(dr), np.concatenate(ac)) for pos, (dr, ac) in cal.items()
    }
    print(f"Range stretch (calibrated on 2015-2017): {factors}")

    proj = []
    for season in SEASONS:
        d_fit = kdef.fit_defense(dg_rows[dg_rows["season"] < season])
        k_fit = kdef.fit_kicker(kg_rows[kg_rows["season"] < season])
        d = dg_rows[dg_rows["season"] == season]
        k = kg_rows[kg_rows["season"] == season].merge(main_k, on=["game_id", "team"])
        dp = d[["game_id", "season", "week", "team"]].assign(
            position="DEF", ours=kdef.project_defense(d, d_fit, scoring)["points"].to_numpy()
        )
        kp = k[["game_id", "season", "week", "team", "gsis_id"]].assign(
            position="K", ours=kdef.project_kicker(k, k_fit, scoring)["points"].to_numpy()
        )
        dd = kdef.stretch(kdef.draw_defense(d, d_fit, scoring, N_DRAWS, rng), factors["DEF"])
        kd = kdef.stretch(kdef.draw_kicker(k, k_fit, scoring, N_DRAWS, rng), factors["K"])
        dp[["q10", "q25", "q75", "q90"]] = np.quantile(dd, [0.1, 0.25, 0.75, 0.9], axis=1).T
        kp[["q10", "q25", "q75", "q90"]] = np.quantile(kd, [0.1, 0.25, 0.75, 0.9], axis=1).T
        for name, frame, cols in [
            ("DEF", d, ["opp_implied", "spread"]),
            ("K", k, ["implied_points", "spread"]),
        ]:
            target = dp if name == "DEF" else kp
            target[cols] = frame[cols].to_numpy()
        proj += [dp, kp]
    proj = pd.concat(proj, ignore_index=True)

    dsl = sl[sl["position"] == "DEF"][["team", "season", "week", "sleeper", "fantasy_points"]]
    ksl = sl[sl["position"] == "K"][["gsis_id", "season", "week", "sleeper", "fantasy_points"]]
    rows = pd.concat(
        [
            proj[proj["position"] == "DEF"].merge(dsl, on=["team", "season", "week"]),
            proj[proj["position"] == "K"].merge(ksl, on=["gsis_id", "season", "week"]),
        ],
        ignore_index=True,
    )

    # Blend and median shift per position on 2018..S-1; direct-points prototype on the same seasons
    rows["blend"] = np.nan
    rows["prototype"] = np.nan
    weights = []
    for pos, feats in [("DEF", ["opp_implied", "spread"]), ("K", ["implied_points", "spread"])]:
        for season in TEST:
            tr = rows[(rows["position"] == pos) & (rows["season"] < season)]
            te = (rows["position"] == pos) & (rows["season"] == season)
            w, shift = pick_blend(tr)
            rows.loc[te, "blend"] = w * rows.loc[te, "ours"] + (1 - w) * rows.loc[te, "sleeper"] + shift
            rows.loc[te, "ours_shifted"] = rows.loc[te, "ours"] + float(
                np.median(tr["fantasy_points"] - tr["ours"])
            )
            qr = QuantileRegressor(quantile=0.5, alpha=0.0, solver="highs").fit(
                tr[feats], tr["fantasy_points"]
            )
            rows.loc[te, "prototype"] = qr.predict(rows.loc[te, feats])
            weights.append({"position": pos, "season": season, "w": w, "shift": shift})
    test = rows[rows["season"].isin(TEST)].copy()
    test["startable"] = (
        test.groupby(["season", "week", "position"])["sleeper"].rank(ascending=False, method="first") <= 12
    )

    out_dir = config.OUTPUT_DIR / "kdef_backtests" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    pd.set_option("display.width", 200)
    for pos in ["DEF", "K"]:
        g = test[test["position"] == pos]
        print(f"\n===== {pos}: {len(g):,} unit-weeks 2019-2025 =====")
        summ = []
        for col in ["sleeper", "prototype", "ours", "ours_shifted", "blend"]:
            rc = (
                g.groupby(["season", "week"])
                .apply(lambda x, c=col: x[c].rank().corr(x["fantasy_points"].rank()), include_groups=False)
                .mean()
            )
            summ.append(
                {
                    "model": col,
                    "MAE": np.mean(np.abs(g[col] - g.fantasy_points)),
                    "MAE startable": np.mean(
                        np.abs(g.loc[g.startable, col] - g.loc[g.startable, "fantasy_points"])
                    ),
                    "rank corr": rc,
                    "bias": (g[col] - g.fantasy_points).mean(),
                }
            )
        print(pd.DataFrame(summ).round(3).to_string(index=False))
        for a, b in [
            ("ours_shifted", "sleeper"),
            ("blend", "sleeper"),
            ("ours_shifted", "prototype"),
            ("blend", "prototype"),
        ]:
            for subset, sub in [("all", g), ("startable", g[g["startable"]])]:
                gap = mae_gap(sub, a, b)
                cc = close_call_gap(_cc_counts(sub, a), _cc_counts(sub, b))
                results.append(
                    {
                        "position": pos,
                        "a": a,
                        "b": b,
                        "rows": subset,
                        **{f"mae_{k}": v for k, v in gap.items()},
                        **{f"cc_{k}": v for k, v in cc.items()},
                    }
                )
                print(
                    f"  {a:12s} vs {b:9s} {subset:9s}: MAE {gap['estimate']:+.3f} ({gap['lo']:+.3f} to {gap['hi']:+.3f}) | "
                    f"close calls {cc['estimate'] * 100:+.1f} pts ({cc['lo'] * 100:+.1f} to {cc['hi'] * 100:+.1f})"
                )
        a = g["fantasy_points"]
        print(
            f"  ranges: 10-90 coverage {np.mean((a >= g.q10) & (a <= g.q90)):.1%}, 25-75 {np.mean((a >= g.q25) & (a <= g.q75)):.1%}"
        )
        w = pd.DataFrame(weights)
        print("  blend weight on ours by season:", w[w.position == pos].set_index("season")["w"].to_dict())
    pd.DataFrame(results).to_csv(out_dir / "kdef_results.csv", index=False)
    test.to_parquet(out_dir / "kdef_scored.parquet", index=False)

    # Live: fits on every season with stats, blend and shift on every Sleeper season
    card = json.loads(config.MODEL_CARD.read_text())
    card["kdef"] = {
        "defense": kdef.fit_defense(dg_rows),
        "kicker": kdef.fit_kicker(kg_rows),
        "blend": {
            pos: dict(zip(("w", "shift"), pick_blend(rows[rows["position"] == pos]))) for pos in ["DEF", "K"]
        },
        "range_stretch": factors,
    }
    config.MODEL_CARD.write_text(json.dumps(card, indent=2) + "\n")
    print(f"\nWrote {out_dir}; model/model_card.json now has 'kdef' (commit it to deploy)")
