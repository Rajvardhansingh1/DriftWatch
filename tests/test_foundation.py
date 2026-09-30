from monitor.config import Settings


def test_settings_load_with_defaults():
    s = Settings(_env_file=None)
    assert s.db_path == "./data/driftwatch.sqlite3"
    assert 0 < s.alert_threshold <= 1
    assert s.canary_interval_minutes > 0


def test_settings_read_env_override(monkeypatch):
    monkeypatch.setenv("DRIFTWATCH_ALERT_THRESHOLD", "0.75")
    s = Settings(_env_file=None)
    assert s.alert_threshold == 0.75
