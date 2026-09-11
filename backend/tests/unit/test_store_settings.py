"""M1.2 configuration persistence tests."""

import json
from pathlib import Path

import pytest

from tonewatch.config.models import AppConfig, ToneSet, ToneSpec
from tonewatch.config.store import ConfigError, ConfigStore
from tonewatch.settings import Settings


def cfg() -> AppConfig:
    return AppConfig(
        tone_sets=[ToneSet(id="page", name="Page", sequence=[ToneSpec(freq_hz=1000, min_s=1)])]
    )


def test_round_trip_default_and_backup(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)
    assert store.load() == AppConfig()
    store.save(cfg())
    assert store.load() == cfg()
    assert (tmp_path / "config.yaml.bak").exists()


def test_atomic_replace_failure_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ConfigStore(tmp_path)
    store.save(cfg())
    original = store.path.read_bytes()
    monkeypatch.setattr(
        "tonewatch.config.store.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("crash"))
    )
    with pytest.raises(ConfigError, match="atomically save"):
        store.save(AppConfig())
    assert store.path.read_bytes() == original


def test_invalid_yaml_is_clear(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("tone_sets: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        ConfigStore(tmp_path).load()


def test_settings_environment_and_addon_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"log_level": "DEBUG", "bind_port": 8123}), encoding="utf-8")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")
    monkeypatch.setenv("TONEWATCH_DATA_DIR", str(tmp_path / "data"))
    settings = Settings.load(options_path=options)
    assert settings.addon_mode is True
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == tmp_path / "data"
