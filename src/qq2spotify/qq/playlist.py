"""Download a QQ Music playlist's song list."""

import html
import json

import httpx

from qq2spotify.models import SourceTrack

# The main address, then a backup that the Listen 1 project uses.
ENDPOINTS = (
    "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg",
    "https://i.y.qq.com/qzone-music/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg",
)


class QQError(RuntimeError):
    """QQ Music didn't return a usable playlist."""


def _parse_body(body: str) -> dict:
    # Some replies wrap the JSON in a callback, like jsonCallback({...}).
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end == -1:
        raise QQError("QQ Music did not return JSON.")
    try:
        return json.loads(body[start : end + 1])
    except json.JSONDecodeError as error:
        raise QQError("QQ Music returned broken JSON.") from error


def fetch_raw(
    playlist_id: str, client: httpx.Client, cookie: str | None = None
) -> dict:
    """Return QQ Music's reply for the playlist, trying the backup address if needed."""
    params = {
        "disstid": playlist_id,
        "type": 1,
        "json": 1,
        "utf8": 1,
        "onlysong": 0,
        "format": "json",
        "loginUin": 0,
    }
    headers = {"Referer": f"https://y.qq.com/n/ryqq/playlist/{playlist_id}"}
    if cookie:
        headers["Cookie"] = cookie
    last_error: Exception | None = None
    for endpoint in ENDPOINTS:
        query = {**params, "nosign": 1} if "i.y.qq.com" in endpoint else params
        try:
            response = client.get(endpoint, params=query, headers=headers)
            response.raise_for_status()
            data = _parse_body(response.text)
        except (httpx.HTTPError, QQError) as error:
            last_error = error
            continue
        if data.get("code") == 0 and data.get("cdlist"):
            return data
        last_error = QQError(
            f"QQ Music returned code {data.get('code')}. The playlist may be "
            "private or deleted; for a login-only playlist, try --qq-cookie."
        )
    if isinstance(last_error, QQError):
        raise last_error
    raise QQError(
        f"Couldn't get the playlist from QQ Music ({last_error})."
    ) from last_error


def _text(value: object) -> str:
    return html.unescape(str(value or "")).strip()


def _duration_ms(interval: object) -> int | None:
    try:
        seconds = int(interval)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return seconds * 1000 if seconds > 0 else None


def parse_playlist(data: dict, playlist_id: str) -> tuple[str, list[SourceTrack]]:
    """Turn QQ Music's reply into the playlist name and its songs, in order.

    Songs without an ID are skipped, and a song that appears twice is kept once,
    at its first position.
    """
    playlist = data["cdlist"][0]
    seen: set[str] = set()
    tracks: list[SourceTrack] = []
    for song in playlist.get("songlist") or playlist.get("list") or []:
        mid = song.get("songmid")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        tracks.append(
            SourceTrack(
                position=len(tracks),
                title=_text(song.get("songname")),
                artists=tuple(
                    _text(singer.get("name"))
                    for singer in song.get("singer") or []
                    if singer.get("name")
                ),
                album=_text(song.get("albumname")) or None,
                duration_ms=_duration_ms(song.get("interval")),
                qq_mid=mid,
            )
        )
    if not tracks:
        raise QQError(
            "The playlist came back empty. It may be login-only; try --qq-cookie."
        )
    name = _text(playlist.get("dissname")) or f"QQ playlist {playlist_id}"
    return name, tracks


def fetch_playlist(
    playlist_id: str, client: httpx.Client, cookie: str | None = None
) -> tuple[str, list[SourceTrack]]:
    """Download a playlist and return its name and songs."""
    return parse_playlist(fetch_raw(playlist_id, client, cookie=cookie), playlist_id)
