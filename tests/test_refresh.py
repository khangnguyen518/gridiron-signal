from datetime import UTC, datetime, timedelta

from nfl_model import alerts, refresh


def test_skips_build_when_sports_db_is_stale(monkeypatch):
    sent, built = [], []
    monkeypatch.setattr(refresh, "sports_db_last_build", lambda: datetime.now(UTC) - timedelta(hours=40))
    monkeypatch.setattr(refresh, "dbt_build", lambda: built.append(1) or 0)
    monkeypatch.setattr(refresh.alerts, "send", sent.append)
    assert refresh.main() == 1
    assert built == [] and "Skipped dbt build" in sent[0]


def test_force_builds_anyway(monkeypatch):
    monkeypatch.setattr(refresh, "sports_db_last_build", lambda: None)
    monkeypatch.setattr(refresh, "dbt_build", lambda: 0)
    monkeypatch.setattr(refresh.alerts, "send", lambda text: None)
    assert refresh.main(force=True) == 0


def test_build_failure_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(refresh, "sports_db_last_build", lambda: datetime.now(UTC) - timedelta(hours=1))
    monkeypatch.setattr(refresh, "dbt_build", lambda: 2)
    monkeypatch.setattr(refresh.alerts, "send", sent.append)
    assert refresh.main() == 2
    assert "failed (exit 2)" in sent[0]


def test_alert_splits_long_messages(monkeypatch):
    posts = []

    class Resp:
        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(alerts, "_webhook_url", lambda: "https://discord.test/hook")
    monkeypatch.setattr(alerts.requests, "post", lambda url, json, timeout: posts.append(json) or Resp())
    assert alerts.send("\n".join(["x" * 100] * 50))
    assert len(posts) == 3
    assert all(len(p["content"]) <= alerts.DISCORD_LIMIT + 1 for p in posts)


def test_alert_without_webhook_only_prints(monkeypatch):
    monkeypatch.setattr(alerts, "_webhook_url", lambda: None)
    assert alerts.send("hello") is False
