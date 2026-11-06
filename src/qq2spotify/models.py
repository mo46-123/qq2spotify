"""Data passed between the parts of qq2spotify."""

from dataclasses import dataclass
from typing import Literal

Status = Literal["matched", "review", "not_found"]


@dataclass(frozen=True)
class SourceTrack:
    """One song read from a QQ Music playlist."""

    position: int  # order in the QQ playlist, from 0
    title: str
    artists: tuple[str, ...]
    album: str | None
    duration_ms: int | None
    qq_mid: str  # QQ song ID (songmid)


@dataclass(frozen=True)
class Candidate:
    """One Spotify search result."""

    uri: str  # spotify:track:...
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int | None
    url: str  # https://open.spotify.com/track/...


@dataclass(frozen=True)
class ScoreParts:
    """How well a candidate matches, part by part (each from 0 to 1)."""

    title: float
    artist: float
    length: float
    album: float
    penalty: float
    total: float


@dataclass(frozen=True)
class MatchResult:
    """The best Spotify candidate found for one QQ song."""

    source: SourceTrack
    status: Status
    best: Candidate | None = None
    parts: ScoreParts | None = None
    query: str | None = None  # the search that found the best candidate
    searches: int = 0

    @property
    def score(self) -> float:
        return self.parts.total if self.parts else 0.0
