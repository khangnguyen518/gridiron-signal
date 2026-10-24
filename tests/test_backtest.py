from nfl_model.backtest import keep_sim_keys

SIM = {"sim": {"n": 1}, "sim_tails": {"QB": 1.0}, "range_mix": {"QB": 0.5}, "residual_table": {"QB": []}}


def test_keeps_range_settings_from_previous_card():
    card = {"params": {"hl_share": 2}}
    full, stale = keep_sim_keys(card, {**card, **SIM})
    assert full == {**card, **SIM}
    assert not stale


def test_flags_ranges_stale_when_model_changed():
    full, stale = keep_sim_keys({"params": {"hl_share": 3}}, {"params": {"hl_share": 2}, **SIM})
    assert full["sim"] == SIM["sim"]
    assert stale


def test_no_previous_card():
    full, stale = keep_sim_keys({"params": {}}, {})
    assert full == {"params": {}}
    assert not stale


def test_blend_shift_is_the_median_miss():
    import pandas as pd

    from nfl_model.backtest import pick_blend_weight

    # Our model and Sleeper agree, so every weight blends to 10; right-skewed actuals
    train = pd.DataFrame(
        {"opp_points": 10.0, "sleeper_projected_points": 10.0, "fantasy_points": [6.0, 7.0, 8.0, 9.0, 30.0]}
    )
    w, c = pick_blend_weight(train, "opp_points")
    assert c == -2.0  # median actual 8 minus the blend's 10, though the mean (12) is above it
    assert pick_blend_weight(train, "opp_points", shift=False) == (w, 0.0)


def test_blend_weight_is_picked_before_the_shift():
    import numpy as np
    import pandas as pd

    from nfl_model.backtest import pick_blend_weight

    # Ours tracks actuals 2 points high; Sleeper is noise around the same level. Picked together,
    # weight and shift would favor ours (w = 1, shift -2); picked first, the weight is unchanged.
    train = pd.DataFrame(
        {
            "opp_points": [12.0, 17.0, 7.0, 22.0],
            "sleeper_projected_points": [15.0, 9.0, 18.0, 11.0],
            "fantasy_points": [10.0, 15.0, 5.0, 20.0],
        }
    )
    w, c = pick_blend_weight(train, "opp_points")
    assert w == pick_blend_weight(train, "opp_points", shift=False)[0]
    blend = w * train["opp_points"] + (1 - w) * train["sleeper_projected_points"]
    assert c == round(float(np.median(train["fantasy_points"] - blend)), 3)
