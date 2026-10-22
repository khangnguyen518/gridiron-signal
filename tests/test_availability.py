import pandas as pd
import pytest

from nfl_model.availability import Renorm, add_team_usual, renormalize

POS = {"QB": 1.0, "RB": 1.0, "WR": 1.0, "TE": 1.0}  # stale-share factors
CENTER = {"target_share": POS, "carry_share": POS, "att_share": 1.0}


def team(rows):
    df = pd.DataFrame(rows)
    df["game_id"], df["team"], df["prior_games"] = "g1", "AAA", 5
    df["position"] = df["position"].fillna("WR") if "position" in df else "WR"
    for col in ["target_share", "carry_share", "att_share", "rz_target_share", "rz_carry_share"]:
        df[col] = df.get(col, 0.0)
    df["usual_target_share"], df["usual_carry_share"] = 1.0, 1.0
    return df


def test_out_starter_shares_go_to_active_players():
    df = team(
        [
            {"gsis_id": "wr1", "active": False, "target_share": 0.30},
            {"gsis_id": "wr2", "active": True, "target_share": 0.35, "rz_target_share": 0.2},
            {"gsis_id": "wr3", "active": True, "target_share": 0.35},
        ]
    )
    out = renormalize(df, "active", Renorm(beta_target=1.0), CENTER)
    active = out[out["active"]]
    assert active["target_share"].sum() == pytest.approx(1.0)
    assert active.loc[active["gsis_id"] == "wr2", "rz_target_share"].item() == pytest.approx(0.2 / 0.7)


def test_missing_wr_targets_stay_with_wrs():
    df = team(
        [
            {"gsis_id": "wr1", "active": False, "target_share": 0.30},
            {"gsis_id": "wr2", "active": True, "target_share": 0.50},
            {"gsis_id": "te1", "active": True, "target_share": 1.0, "position": "TE"},
        ]
    )
    out = renormalize(df, "active", Renorm(beta_target=1.0), CENTER)
    assert out.loc[out["gsis_id"] == "wr2", "target_share"].item() == pytest.approx(1.0)
    assert out.loc[out["gsis_id"] == "te1", "target_share"].item() == pytest.approx(1.0)


def test_beta_zero_changes_nothing():
    df = team(
        [
            {"gsis_id": "a", "active": False, "target_share": 0.5},
            {"gsis_id": "b", "active": True, "target_share": 0.5},
        ]
    )
    out = renormalize(df, "active", Renorm(), CENTER)
    assert list(out["target_share"]) == [0.5, 0.5]


def test_backup_qb_takes_over_attempts():
    df = team(
        [
            {"gsis_id": "qb1", "active": False, "att_share": 0.98, "position": "QB"},
            {"gsis_id": "qb2", "active": True, "att_share": 0.04, "position": "QB"},
        ]
    )
    out = renormalize(df, "active", Renorm(beta_att=1.0), CENTER)
    assert out.loc[out["gsis_id"] == "qb2", "att_share"].item() == pytest.approx(1.0)


def test_scale_is_clipped():
    df = team(
        [
            {"gsis_id": "a", "active": False, "target_share": 0.9},
            {"gsis_id": "b", "active": True, "target_share": 0.1},
        ]
    )
    out = renormalize(df, "active", Renorm(beta_target=1.0), CENTER)
    assert out.loc[out["gsis_id"] == "b", "target_share"].item() == pytest.approx(0.2)  # 2x clip


def test_stale_backup_share_does_not_shrink_starter():
    df = team(
        [
            {"gsis_id": "qb1", "active": True, "att_share": 1.0, "position": "QB"},
            {"gsis_id": "qb2", "active": True, "att_share": 0.9, "position": "QB"},
        ]
    )
    out = renormalize(df, "active", Renorm(beta_att=1.0), CENTER)
    assert out.loc[out["gsis_id"] == "qb1", "att_share"].item() == pytest.approx(1.0)


def test_rare_groups_are_left_alone():
    df = team([{"gsis_id": "qb1", "active": True, "target_share": 0.01, "position": "QB"}])
    out = renormalize(df, "active", Renorm(beta_target=1.0), CENTER)
    assert out["target_share"].item() == pytest.approx(0.01)


def test_team_usual_uses_earlier_games_of_that_team():
    games = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "team": "AAA",
            "kickoff_utc": pd.to_datetime(["2025-09-07", "2025-09-14", "2025-09-21"]),
        }
    )
    feats = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "team": "AAA",
            "position": "TE",
            "played": [1, 1, 0],
            "targets": [10, 20, 0],
            "team_pass_attempts": [40, 40, 0],
            "carries": 0,
            "team_rush_attempts": [20, 20, 0],
        }
    )
    out = add_team_usual(feats, games, half_life=1.0).set_index("game_id")
    assert pd.isna(out.loc["g1", "usual_target_share"])
    assert out.loc["g2", "usual_target_share"] == pytest.approx(0.25)
    # g3: g2 (0.5) at weight 1, g1 (0.25) at weight 0.5
    assert out.loc["g3", "usual_target_share"] == pytest.approx((0.5 + 0.5 * 0.25) / 1.5)
