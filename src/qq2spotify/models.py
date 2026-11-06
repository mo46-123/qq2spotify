"""Data passed between the parts of qq2spotify."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceTrack:
    """One song read from a QQ Music playlist."""

    position: int  # order in the QQ playlist, from 0
    title: str
    artists: tuple[str, ...]
    album: str | None
    duration_ms: int | None
    qq_mid: str  # QQ song ID (songmid)
