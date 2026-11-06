"""Turn whatever the user pastes into a QQ Music playlist ID."""

import re
from urllib.parse import parse_qs, urlparse

import httpx

# URLs are plain ASCII, so a link ends at the first space or non-ASCII
# character, such as Chinese text or punctuation right after it.
URL_RE = re.compile(r"https?://[!-~]+")
DIGITS_RE = re.compile(r"[0-9]+")
SHORT_HOSTS = {"c.y.qq.com", "c6.y.qq.com"}
NOT_PLAYLIST = ("songDetail", "albumDetail", "songmid=")


class LinkError(ValueError):
    """The input doesn't contain a usable QQ Music playlist link."""


def extract_playlist_id(text: str, client: httpx.Client) -> str:
    """Return the playlist ID (QQ calls it disstid) from a link, share text or ID.

    Short links are followed with ``client``, so this may make one request.
    """
    text = text.strip()
    if DIGITS_RE.fullmatch(text):
        return text
    match = URL_RE.search(text)
    if not match:
        raise LinkError("No link found. Paste a QQ Music playlist link.")
    url = match.group(0)
    if urlparse(url).hostname in SHORT_HOSTS and "/base/fcgi-bin/u" in url:
        url = str(client.get(url, follow_redirects=True).url)
    if any(marker in url for marker in NOT_PLAYLIST):
        raise LinkError("This is a song or album link, not a playlist link.")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("id", "disstid", "dissid"):
        found = DIGITS_RE.match(query.get(key, [""])[0])
        if found:
            return found.group(0)
    found = re.search(r"/playlist/([0-9]+)", parsed.path)
    if found:
        return found.group(1)
    raise LinkError(f"Couldn't find a playlist ID in {url}")
