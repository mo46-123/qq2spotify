"""Score how well a Spotify search result matches a QQ Music song."""

from collections.abc import Iterable, Mapping, Sequence

from rapidfuzz import fuzz

from qq2spotify.matching.normalize import (
    album_tags,
    clean,
    is_east_asian_name,
    is_latin_name,
    name_variants,
    split_title,
)
from qq2spotify.models import Candidate, ScoreParts, SourceTrack, Status

MATCHED = 0.80  # added to the playlist
REVIEW = 0.60  # listed in the report for a person to check
TITLE_WEIGHT = 0.45
ARTIST_WEIGHT = 0.35
LENGTH_WEIGHT = 0.15
ALBUM_WEIGHT = 0.05
EXTRA_VERSION_PENALTY = 0.30  # Spotify's song is a live, karaoke, ... version
MISSING_VERSION_PENALTY = 0.15  # QQ's song is such a version, Spotify's isn't
# Artist score when Spotify's own artist search linked QQ's Chinese name to an
# English one, like 李圣杰 to Sam Lee, which plain text comparison can't see.
CONFIRMED_BY_SEARCH = 0.85

# Cleaned Chinese artist name -> names Spotify may use, e.g. "周杰伦" -> ["Jay Chou"].
Aliases = Mapping[str, Sequence[str]]


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.ratio(a, b) / 100


def length_score(a_ms: int | None, b_ms: int | None) -> float:
    """1.0 within 3 seconds, falling to 0 at 15 seconds; 0.5 if a length is missing."""
    if not a_ms or not b_ms:
        return 0.5
    difference = abs(a_ms - b_ms) / 1000
    if difference <= 3:
        return 1.0
    return max(0.0, 1 - (difference - 3) / 12)


def artist_variants(names: Iterable[str], aliases: Aliases) -> set[str]:
    variants: set[str] = set()
    for name in names:
        for variant in name_variants(name):
            variants.add(variant)
            for alias in aliases.get(variant, ()):
                variants |= name_variants(alias)
    return variants


def _confirmed_by_search(
    artist_filter: str | None, candidate: Candidate, title: float, length: float
) -> bool:
    """Spotify found this track when searching with QQ's own Chinese spelling of
    the singer, and lists the singer under a Latin name: Spotify linked them."""
    return bool(
        artist_filter
        and is_east_asian_name(artist_filter)
        and candidate.artists
        and all(is_latin_name(name) for name in candidate.artists)
        and title >= 0.9
        and length >= 0.75
    )


def score_candidate(
    track: SourceTrack,
    candidate: Candidate,
    aliases: Aliases,
    artist_filter: str | None = None,
) -> ScoreParts:
    """Score a candidate. ``artist_filter`` is the QQ spelling of the singer used
    in the search's artist: filter, if there was one."""
    ours, theirs = split_title(track.title), split_title(candidate.title)
    title = similarity(clean(ours.core), clean(theirs.core))
    wanted = artist_variants((*track.artists, *ours.featured), aliases)
    found = artist_variants((*candidate.artists, *theirs.featured), {})
    artist = max((similarity(a, b) for a in wanted for b in found), default=0.0)
    length = length_score(track.duration_ms, candidate.duration_ms)
    artist_by_search = False
    if artist < CONFIRMED_BY_SEARCH and _confirmed_by_search(
        artist_filter, candidate, title, length
    ):
        artist, artist_by_search = CONFIRMED_BY_SEARCH, True
    if track.album and candidate.album:
        album = similarity(clean(track.album), clean(candidate.album))
    else:
        album = 0.5
    # A concert album makes a song a live version even without "Live" in its title.
    our_tags = ours.tags | album_tags(track.album)
    their_tags = theirs.tags | album_tags(candidate.album)
    penalty = 0.0
    if their_tags - our_tags:
        penalty += EXTRA_VERSION_PENALTY
    if our_tags - their_tags:
        penalty += MISSING_VERSION_PENALTY
    total = (
        TITLE_WEIGHT * title
        + ARTIST_WEIGHT * artist
        + LENGTH_WEIGHT * length
        + ALBUM_WEIGHT * album
        - penalty
    )
    return ScoreParts(
        title=round(title, 3),
        artist=round(artist, 3),
        length=round(length, 3),
        album=round(album, 3),
        penalty=round(penalty, 2),
        total=round(max(0.0, min(1.0, total)), 3),
        artist_by_search=artist_by_search,
    )


def status_for(total: float) -> Status:
    if total >= MATCHED:
        return "matched"
    if total >= REVIEW:
        return "review"
    return "not_found"
