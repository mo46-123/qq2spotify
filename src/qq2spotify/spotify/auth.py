"""Spotify login (Authorization Code with PKCE) and saved logins."""

import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import socketserver
import string
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from qq2spotify.config import Settings

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private"
VERIFIER_ALPHABET = string.ascii_letters + string.digits + "_.-~"
ACCOUNT_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
REFRESH_MARGIN_SECONDS = 60
# Spotify refresh tokens stop working 6 months after the original login.
LOGIN_WARNING_DAYS = 165


class LoginError(RuntimeError):
    """Signing in didn't work."""


class NeedsLogin(RuntimeError):
    """There is no usable saved login; the user has to run qq2spotify login."""


def code_challenge(verifier: str) -> str:
    """Return the PKCE code challenge: base64url(SHA-256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> tuple[str, str]:
    """Return a random 64-character code verifier and its code challenge."""
    verifier = "".join(secrets.choice(VERIFIER_ALPHABET) for _ in range(64))
    return verifier, code_challenge(verifier)


@dataclass(frozen=True)
class LoginAttempt:
    url: str
    verifier: str
    state: str


def start_login(settings: Settings) -> LoginAttempt:
    """Prepare the Spotify page the user has to open to log in."""
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(16)
    query = urlencode(
        {
            "client_id": settings.client_id,
            "response_type": "code",
            "redirect_uri": settings.redirect_uri,
            "scope": SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
            # Always show Spotify's consent page, so people can switch accounts.
            "show_dialog": "true",
        }
    )
    return LoginAttempt(url=f"{AUTH_URL}?{query}", verifier=verifier, state=state)


def parse_callback(text: str) -> dict[str, str]:
    """Read code, state or error from the address the browser ended on."""
    text = text.strip()
    query = urlparse(text).query if "://" in text else text.lstrip("?")
    return {key: values[0] for key, values in parse_qs(query).items()}


class _LocalServer(HTTPServer):
    """An HTTPServer that skips the host-name lookup, which is slow on some PCs."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def wait_for_callback(
    port: int, path: str = "/callback", timeout: float = 300
) -> dict[str, str]:
    """Run a one-off web server on 127.0.0.1 and return Spotify's reply."""
    reply: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != path:
                self.send_error(404)
                return
            reply.update({k: v[0] for k, v in parse_qs(parsed.query).items()})
            body = b"qq2spotify: done. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass  # keep the terminal quiet

    try:
        server = _LocalServer(("127.0.0.1", port), Handler)
    except OSError as error:
        raise LoginError(
            f"Couldn't listen on port {port} ({error}). Close the program using it, "
            "or pick another port in SPOTIFY_REDIRECT_URI and in your Spotify app."
        ) from error
    deadline = time.monotonic() + timeout
    with server:
        while "code" not in reply and "error" not in reply:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LoginError("Timed out waiting for the Spotify login.")
            # Wake up often so Ctrl+C works quickly, including on Windows.
            server.timeout = min(remaining, 0.5)
            server.handle_request()
    return reply


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(data, dict):
        return str(data.get("error_description") or data.get("error") or data)
    return f"HTTP {response.status_code}"


def _error_code(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data.get("error") if isinstance(data, dict) else None


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float
    scope: str
    authorized_at: str
    spotify_user_id: str
    display_name: str

    def days_since_login(self, now: float | None = None) -> int:
        logged_in = datetime.fromisoformat(self.authorized_at).timestamp()
        current = time.time() if now is None else now
        return max(0, int((current - logged_in) // 86400))


def finish_login(
    attempt: LoginAttempt,
    reply: dict[str, str],
    settings: Settings,
    http: httpx.Client,
    now: float | None = None,
) -> TokenSet:
    """Check Spotify's reply, swap the code for tokens and read the account name."""
    if "error" in reply:
        raise LoginError(f"Spotify login didn't finish ({reply['error']}).")
    if reply.get("state") != attempt.state:
        raise LoginError(
            "That reply doesn't belong to this login. Run qq2spotify login again."
        )
    code = reply.get("code")
    if not code:
        raise LoginError("Spotify's reply had no code. Run qq2spotify login again.")
    response = http.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "client_id": settings.client_id,
            "code_verifier": attempt.verifier,
        },
    )
    if response.status_code >= 400:
        raise LoginError(f"Spotify refused the login ({_error_text(response)}).")
    token = response.json()
    profile = http.get(
        f"{API_URL}/me", headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    if profile.status_code == 403:
        raise LoginError(
            "Spotify won't let this account use your app yet. Add it under User "
            "Management in your Spotify app's settings (the app owner also needs "
            "Premium), then run qq2spotify login again."
        )
    profile.raise_for_status()
    me = profile.json()
    stamp = time.time() if now is None else now
    return TokenSet(
        access_token=token["access_token"],
        refresh_token=token["refresh_token"],
        expires_at=stamp + int(token.get("expires_in", 3600)),
        scope=token.get("scope", ""),
        authorized_at=datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds"),
        spotify_user_id=me["id"],
        display_name=me.get("display_name") or me["id"],
    )


class TokenStore:
    """Saved logins: one JSON file per account nickname."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def path(self, account: str) -> Path:
        if not ACCOUNT_RE.fullmatch(account):
            raise ValueError(
                "Account names can only use letters, digits, - and _ (40 at most)."
            )
        return self.folder / f"{account}.json"

    def load(self, account: str) -> TokenSet:
        path = self.path(account)
        hint = f"Run: qq2spotify login --account {account}"
        try:
            return TokenSet(**json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise NeedsLogin(f"No saved login named {account!r}. {hint}") from None
        except (ValueError, TypeError) as error:
            raise NeedsLogin(
                f"The saved login {account!r} is damaged. {hint}"
            ) from error

    def save(self, account: str, tokens: TokenSet) -> None:
        path = self.path(account)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(tokens), indent=2), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(temporary, 0o600)  # only you can read it (where supported)
        os.replace(temporary, path)

    def delete(self, account: str) -> bool:
        try:
            self.path(account).unlink()
        except FileNotFoundError:
            return False
        return True

    def accounts(self) -> list[str]:
        if not self.folder.is_dir():
            return []
        return sorted(
            p.stem for p in self.folder.glob("*.json") if ACCOUNT_RE.fullmatch(p.stem)
        )


class AccountTokens:
    """Hands out a fresh access token for one saved account, refreshing it as needed."""

    def __init__(
        self,
        store: TokenStore,
        account: str,
        client_id: str,
        http: httpx.Client,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.account = account
        self.client_id = client_id
        self.http = http
        self.clock = clock
        self.tokens = store.load(account)

    def access_token(self) -> str:
        if self.tokens.expires_at - self.clock() < REFRESH_MARGIN_SECONDS:
            self.refresh()
        return self.tokens.access_token

    def refresh(self) -> None:
        response = self.http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.tokens.refresh_token,
                "client_id": self.client_id,
            },
        )
        if (
            response.status_code in (400, 401)
            and _error_code(response) == "invalid_grant"
        ):
            self.store.delete(self.account)
            raise NeedsLogin(
                f"The saved login {self.account!r} has expired or was removed "
                "(Spotify logins last 6 months). "
                f"Run: qq2spotify login --account {self.account}"
            )
        response.raise_for_status()
        token = response.json()
        self.tokens.access_token = token["access_token"]
        self.tokens.expires_at = self.clock() + int(token.get("expires_in", 3600))
        self.tokens.refresh_token = (
            token.get("refresh_token") or self.tokens.refresh_token
        )
        self.tokens.scope = token.get("scope") or self.tokens.scope
        self.store.save(self.account, self.tokens)
