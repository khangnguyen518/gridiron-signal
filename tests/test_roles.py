import numpy as np
import pandas as pd
import pytest

from nfl_model.roles import RoleParams, add_role_curves, assign_roles, shrink_to_roles


def week(game: str, day: str, players: list[tuple]) -> list[dict]:
    """players: (gsis_id, position, depth_tier, target_share, carry_share, targets, carries)."""
    return [
        {
            "game_id": game,
            "team": "AAA",
            "kickoff_utc": pd.Timestamp(day),
            "active": True,
            "gsis_id": g,
            "position": pos,
            "depth_tier": tier,
            "target_share": ts,
            "carry_share": cs,
            "rz_target_share": ts,
            "rz_carry_share": cs,
            "targets": t,
            "carries": c,
            "team_pass_attempts": 40.0,
            "team_rush_attempts": 25.0,
            "share_games": 4.0,
        }
        for g, pos, tier, ts, cs, t, c in players
    ]


def test_depth_rule_puts_a_new_starter_ahead_of_a_bigger_share():
    df = pd.DataFrame(
        week(
            "g1",
            "2025-09-07",
            [
                ("wr_a", "WR", 2, 0.25, 0, 10, 0),  # backup with the bigger recent share
                ("wr_b", "WR", 1, 0.10, 0, 4, 0),  # just named a starter
                ("rb_a", "RB", 1, 0.05, 0.6, 2, 15),
            ],
        )
    )
    assert list(assign_roles(df, "active", "depth")) == [2, 1, 1]
    assert list(assign_roles(df, "active", "share")) == [1, 2, 1]


def test_role_curves_use_earlier_games_only():
    rows = week("g1", "2025-09-07", [("wr_a", "WR", 1, 0.3, 0, 12, 0), ("wr_b", "WR", 1, 0.2, 0, 8, 0)])
    rows += week("g2", "2025-09-14", [("wr_a", "WR", 1, 0.3, 0, 16, 0), ("wr_b", "WR", 1, 0.2, 0, 4, 0)])
    df = pd.DataFrame(rows)
    out = add_role_curves(df, assign_roles(df, "active", "depth"), hl_role=1e9)
    g2_wr1 = out[(out.game_id == "g2") & (out.role == 1)]
    assert g2_wr1["curve_target"].item() == pytest.approx(12 / 40)  # WR1's share in g1 only
    assert out[out.game_id == "g1"]["curve_target"].isna().all()


def test_shrink_pulls_toward_curve_by_games_played():
    df = pd.DataFrame(week("g1", "2025-09-07", [("wr_a", "WR", 1, 0.10, 0, 0, 0)]))
    df["role"], df["curve_target"], df["curve_carry"] = 1.0, 0.30, np.nan
    out = shrink_to_roles(df, RoleParams(k_target=4.0))
    assert out["target_share"].item() == pytest.approx((4 * 0.10 + 4 * 0.30) / 8)
    assert out["rz_target_share"].item() == pytest.approx(0.10 * out["target_share"].item() / 0.10)


def test_zero_pull_changes_nothing():
    df = pd.DataFrame(week("g1", "2025-09-07", [("rb_a", "RB", 1, 0.05, 0.4, 2, 10)]))
    df["role"], df["curve_target"], df["curve_carry"] = 1.0, 0.1, 0.7
    out = shrink_to_roles(df, RoleParams())
    assert out["carry_share"].item() == 0.4
