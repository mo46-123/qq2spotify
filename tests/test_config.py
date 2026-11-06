from pathlib import Path

import pytest

from qq2spotify.config import (
    DEFAULT_REDIRECT_URI,
    ConfigError,
    data_dir,
    load_settings,
)

NAMES = ("SPOTIFY_CLIENT_ID", "SPOTIFY_REDIRECT_URI", "QQ2SPOTIFY_HOME")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # setenv first so monkeypatch puts each variable back the way it was after
    # the test, even when load_settings() set it from a .env file.
    for name in NAMES:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def write_env(folder: Path, text: str) -> None:
    (folder / ".env").write_text(text, encoding="utf-8")


def test_reads_the_env_file_in_the_current_folder(tmp_path: Path) -> None:
    write_env(tmp_path, "SPOTIFY_CLIENT_ID=abc123\n")
    settings = load_settings()
    assert settings.client_id == "abc123"
    assert settings.redirect_uri == DEFAULT_REDIRECT_URI
    assert settings.callback_port == 8888
    assert settings.callback_path == "/callback"


def test_environment_variables_win_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_env(tmp_path, "SPOTIFY_CLIENT_ID=from-file\n")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "from-environment")
    assert load_settings().client_id == "from-environment"


def test_custom_port_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "abc123")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:9090/done")
    settings = load_settings()
    assert settings.callback_port == 9090
    assert settings.callback_path == "/done"


@pytest.mark.parametrize("env_text", ["", "SPOTIFY_CLIENT_ID=paste-your-client-id\n"])
def test_missing_client_id_explains_what_to_do(tmp_path: Path, env_text: str) -> None:
    write_env(tmp_path, env_text)
    with pytest.raises(ConfigError, match=r"\.env"):
        load_settings()


@pytest.mark.parametrize(
    ("redirect_uri", "message"),
    [
        ("http://localhost:8888/callback", "localhost"),
        ("https://example.com/callback", "must look like"),
        ("http://127.0.0.1/callback", "must look like"),
    ],
)
def test_bad_redirect_uri(
    monkeypatch: pytest.MonkeyPatch, redirect_uri: str, message: str
) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "abc123")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", redirect_uri)
    with pytest.raises(ConfigError, match=message):
        load_settings()


def test_data_dir_can_be_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QQ2SPOTIFY_HOME", str(tmp_path / "home"))
    assert data_dir() == tmp_path / "home"


def test_data_dir_default_is_named_after_the_tool() -> None:
    assert data_dir().name == "qq2spotify"
