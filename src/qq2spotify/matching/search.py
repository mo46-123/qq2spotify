"""Find a QQ Music song on Spotify with a short cascade of searches."""

import json
import time
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

from qq2spotify.matching.chinese import to_hongkong, to_taiwan
from qq2spotify.matching.normalize import clean, search_names, split_title
from qq2spotify.matching.score import MATCHED, Aliases, score_candidate, status_for
from qq2spotify.models import Candidate, MatchResult, ScoreParts, SourceTrack

MAX_SEARCHES = 6
RESULTS_PER_SEARCH = 10  # Spotify's maximum since February 2026


class SearchApi(Protocol):
    def get(self, path: str, **kwargs: Any) -> dict: ...


def load_aliases(extra_file: Path | None = None) -> dict[str, list[str]]:
    """Load the bundled artist names, plus the user's own file if it exists.

    Both files map a Chinese name to the names Spotify uses, for example
    {"周杰伦": ["Jay Chou"]}. The user's file wins when both list a name.
    """
    bundled = resources.files("qq2spotify.matching").joinpath("aliases.json")
    raw: dict = json.loads(bundled.read_text(encoding="utf-8"))
    if extra_file is not None and extra_file.is_file():
        raw.update(json.loads(extra_file.read_text(encoding="utf-8")))
    aliases: dict[str, list[str]] = {}
    for name, others in raw.items():
        names = [others] if isinstance(others, str) else list(others)
        aliases[clean(name)] = [other for other in names if other]
    return aliases


def _names_to_search(track: SourceTrack, aliases: Aliases) -> list[str]:
    """The first singer's names: Spotify's spellings first, then QQ's own."""
    if not track.artists:
        return []
    singer = track.artists[0]
    own = search_names(singer)  # ["G.E.M.", "邓紫棋"] for "G.E.M.邓紫棋"
    keys = [clean(singer), *(clean(name) for name in own)]
    spotify_names = [alias for key in keys for alias in aliases.get(key, ())]
    return list(dict.fromkeys([*spotify_names, *own]))


def build_queries(track: SourceTrack, aliases: Aliases) -> list[str]:
    """The searches to try, best first: at most 6, without repeats."""
    core = split_title(track.title).core
    names = _names_to_search(track, aliases)
    queries: list[str] = []
    if names:
        first = names[0]
        queries.append(f"track:{core} artist:{first}")
        queries.append(f"track:{to_taiwan(core)} artist:{first}")
        if len(names) > 1:
            queries.append(f"track:{core} artist:{names[1]}")
        queries.append(f"{core} {first}")
        queries.append(f"track:{to_hongkong(core)} artist:{first}")
    queries.append(f"track:{core}")
    return list(dict.fromkeys(queries))[:MAX_SEARCHES]


def _candidate(item: dict | None) -> Candidate | None:
    if not item or item.get("is_local") or item.get("is_playable") is False:
        return None
    if not item.get("uri"):
        return None
    return Candidate(
        uri=item["uri"],
        title=item.get("name") or "",
        artists=tuple(
            artist["name"]
            for artist in item.get("artists") or []
            if artist and artist.get("name")
        ),
        album=(item.get("album") or {}).get("name") or "",
        duration_ms=item.get("duration_ms"),
        url=(item.get("external_urls") or {}).get("spotify") or "",
    )


class Matcher:
    """Searches Spotify for QQ songs and keeps the best-scoring result."""

    def __init__(
        self,
        api: SearchApi,
        aliases: Aliases | None = None,
        pause: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api = api
        self.aliases = aliases or {}
        self.pause = pause  # seconds between searches, to stay under rate limits
        self.sleep = sleep
        self.searches_sent = 0

    def search(self, query: str) -> list[Candidate]:
        if self.searches_sent and self.pause:
            self.sleep(self.pause)
        self.searches_sent += 1
        data = self.api.get(
            "/search",
            params={"q": query, "type": "track", "limit": RESULTS_PER_SEARCH},
        )
        items = (data.get("tracks") or {}).get("items") or []
        return [found for found in map(_candidate, items) if found is not None]

    def match(self, track: SourceTrack) -> MatchResult:
        best: Candidate | None = None
        best_parts: ScoreParts | None = None
        best_query: str | None = None
        searches = 0
        for query in build_queries(track, self.aliases):
            searches += 1
            for candidate in self.search(query):
                parts = score_candidate(track, candidate, self.aliases)
                if best_parts is None or parts.total > best_parts.total:
                    best, best_parts, best_query = candidate, parts, query
            if best_parts is not None and best_parts.total >= MATCHED:
                break
        return MatchResult(
            source=track,
            status=status_for(best_parts.total if best_parts else 0.0),
            best=best,
            parts=best_parts,
            query=best_query,
            searches=searches,
        )
