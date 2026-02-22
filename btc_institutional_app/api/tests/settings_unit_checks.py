from pathlib import Path

from app.services import settings


def test_read_secret_value_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PIONEX_API_KEY", "env-value")
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("file-value")
    monkeypatch.setenv("PIONEX_API_KEY_FILE", str(secret_file))

    assert settings.read_secret_value("PIONEX_API_KEY", "") == "env-value"


def test_read_secret_value_uses_file(monkeypatch, tmp_path):
    monkeypatch.delenv("PIONEX_API_SECRET", raising=False)
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("file-secret\n")
    monkeypatch.setenv("PIONEX_API_SECRET_FILE", str(secret_file))

    assert settings.read_secret_value("PIONEX_API_SECRET", "") == "file-secret"


def test_read_secret_value_returns_default_on_missing_file(monkeypatch):
    monkeypatch.delenv("EVENT_CALENDAR_URL", raising=False)
    monkeypatch.setenv("EVENT_CALENDAR_URL_FILE", "/not/existing/path")

    assert settings.read_secret_value("EVENT_CALENDAR_URL", "fallback") == "fallback"


def test_load_settings_reads_write_token(monkeypatch):
    monkeypatch.setenv("API_WRITE_TOKEN", "token-1")
    cfg = settings.load_settings()
    assert cfg.write_token == "token-1"
