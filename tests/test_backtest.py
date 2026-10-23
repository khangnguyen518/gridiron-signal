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
