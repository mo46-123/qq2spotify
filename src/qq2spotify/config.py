"""Settings and folders."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv
from platformdirs import user_config_path

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
PLACEHOLDER_CLIENT_ID = "paste-your-client-id"


class ConfigError(RuntimeError):
    """A setting is missing or wrong."""


@dataclass(frozen=True)
class Settings:
    client_id: str
    redirect_uri: str

    @property
    def callback_port(self) -> int:
        return urlparse(self.redirect_uri).port or 80

    @property
    def callback_path(self) -> str:
        return urlparse(self.redirect_uri).path or "/"


def load_settings() -> Settings:
    """Read settings from environment variables or a .env file.

    The .env file is looked for in the current folder and the folders above it.
    Environment variables that are already set win over the file.
    """
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path)
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    if not client_id or client_id == PLACEHOLDER_CLIENT_ID:
        raise ConfigError(
            "SPOTIFY_CLIENT_ID isn't set. Copy .env.example to .env in the folder "
            "you run qq2spotify from, and paste your Spotify app's Client ID into it."
        )
    redirect_uri = (
        os.environ.get("SPOTIFY_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI
    )
    parsed = urlparse(redirect_uri)
    if parsed.hostname == "localhost":
        raise ConfigError(
            "Spotify refuses localhost in redirect URIs. Use "
            f"{DEFAULT_REDIRECT_URI} here and in your Spotify app's settings."
        )
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise ConfigError(
            f"SPOTIFY_REDIRECT_URI must look like {DEFAULT_REDIRECT_URI} "
            f"(it is {redirect_uri})."
        )
    return Settings(client_id=client_id, redirect_uri=redirect_uri)


def data_dir() -> Path:
    """Folder for saved logins and caches. QQ2SPOTIFY_HOME overrides it."""
    override = os.environ.get("QQ2SPOTIFY_HOME", "").strip()
    if override:
        return Path(override)
    return user_config_path("qq2spotify", appauthor=False)
