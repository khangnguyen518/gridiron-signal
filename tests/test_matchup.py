import numpy as np
import pandas as pd

from nfl_model.matchup import K_PLAYERS, fit_weight, player_signal, points_allowed


def _games() -> pd.DataFrame:
    """Two TEs, each averaging 10 points against other defenses, then each facing DEF in turn."""
    rows = []
    week = 0
    for gsis, team in [("te1", "A"), ("te2", "B")]:
        for _ in range(3):
            week += 1
            rows.append((f"g{week}", gsis, "TE", team, "OTHER", 10.0, week))
    rows.append(("g10", "te1", "TE", "A", "DEF", 16.0, 10))  # 6 over his usual against DEF
    rows.append(("g11", "te2", "TE", "B", "DEF", 13.0, 11))  # 3 over his usual
    df = pd.DataFrame(
        rows, columns=["game_id", "gsis_id", "position", "team", "opponent", "fantasy_points", "w"]
    )
    df["kickoff_utc"] = pd.Timestamp("2024-09-01") + pd.to_timedelta(df.pop("w") * 7, unit="D")
    return df


def test_points_allowed_uses_only_earlier_games_and_players_own_baselines():
    pg = _games()
    allowed = points_allowed(pg).set_index(["game_id", "defense"])
    assert allowed.loc[("g10", "DEF"), "pa_TE"] == 0.0  # DEF's first game: no history yet
    # Before g11, DEF allowed one TE game at +6 over his own average, shrunk by the pseudo-players
    assert np.isclose(allowed.loc[("g11", "DEF"), "pa_TE"], 6.0 / (1 + K_PLAYERS))


def test_points_allowed_ignores_the_current_game():
    pg = _games()
    changed = pg.assign(fantasy_points=np.where(pg["game_id"] == "g11", 40.0, pg["fantasy_points"]))
    a = points_allowed(pg).set_index(["game_id", "defense"]).loc[("g11", "DEF"), "pa_TE"]
    b = points_allowed(changed).set_index(["game_id", "defense"]).loc[("g11", "DEF"), "pa_TE"]
    assert abs(a - b) < 1e-9  # equal up to float roundoff: lagged_wsum subtracts the current game


def test_upcoming_game_gets_the_latest_history():
    pg = _games()
    upcoming = pd.DataFrame(
        {"game_id": ["g12"], "defense": ["DEF"], "kickoff_utc": [pd.Timestamp("2024-12-01")]}
    )
    allowed = points_allowed(pg, upcoming)
    rows = pd.DataFrame({"game_id": ["g12", "g12"], "opponent": ["DEF", "DEF"], "position": ["TE", "WR"]})
    sig = player_signal(rows, allowed)
    assert sig.iloc[0] > 6.0 / (1 + K_PLAYERS)  # both TE games now count
    assert sig.iloc[1] == 0.0  # no WR history against DEF


def test_fit_weight_recovers_slope_without_intercept():
    rng = np.random.default_rng(0)
    signal = pd.Series(rng.normal(0, 1, 2000))
    miss = 0.2 * signal + pd.Series(rng.laplace(0, 0.5, 2000))
    assert abs(fit_weight(miss, signal) - 0.2) < 0.05
    assert fit_weight(miss[:50], signal[:50]) == 0.0  # too few rows
