import pytest

from qq2spotify.matching.score import (
    MATCHED,
    REVIEW,
    length_score,
    score_candidate,
    status_for,
)
from qq2spotify.models import Candidate, SourceTrack

ALIASES = {"周杰伦": ["Jay Chou"], "五月天": ["Mayday"]}


def song(
    title: str, artists: list[str], album: str | None = None, seconds: float = 0
) -> SourceTrack:
    duration = int(seconds * 1000) or None
    return SourceTrack(0, title, tuple(artists), album, duration, "mid")


def found(
    title: str, artists: list[str], album: str = "", seconds: float = 0
) -> Candidate:
    duration = int(seconds * 1000) or None
    return Candidate("spotify:track:x", title, tuple(artists), album, duration, "")


def test_traditional_album_and_english_artist_name_match() -> None:
    parts = score_candidate(
        song("晴天", ["周杰伦"], "叶惠美", 269),
        found("晴天", ["Jay Chou"], "葉惠美", 269.5),
        ALIASES,
    )
    assert parts.total == 1.0
    assert status_for(parts.total) == "matched"


def test_unknown_english_name_needs_review() -> None:
    parts = score_candidate(
        song("晴天", ["周杰伦"], "叶惠美", 269),
        found("晴天", ["Jay Chou"], "葉惠美", 269.5),
        {},
    )
    assert parts.artist == 0.0
    assert REVIEW <= parts.total < MATCHED


def test_traditional_title_with_alias() -> None:
    parts = score_candidate(
        song("后来的我们", ["五月天"], "自传", 346),
        found("後來的我們", ["Mayday"], "自傳", 346),
        ALIASES,
    )
    assert parts.total == 1.0


def test_mixed_name_matches_its_latin_half() -> None:
    parts = score_candidate(
        song("喜欢你", ["G.E.M.邓紫棋"], "喜欢你", 239),
        found("喜歡你", ["G.E.M."], "喜歡你", 239),
        {},
    )
    assert parts.artist == 1.0
    assert parts.total == 1.0


def test_featured_artist_in_the_title_counts() -> None:
    parts = score_candidate(
        song("说好不哭（with 五月天阿信）", ["周杰伦"], "说好不哭", 222),
        found("說好不哭", ["五月天阿信"], "說好不哭", 222),
        {},
    )
    assert parts.artist == 1.0


def test_live_version_does_not_match_the_studio_song() -> None:
    parts = score_candidate(
        song("晴天", ["周杰伦"], "叶惠美", 269),
        found("晴天 - Live", ["Jay Chou"], "地表最強世界巡迴演唱會", 280),
        ALIASES,
    )
    assert parts.penalty == 0.3
    assert parts.total < MATCHED


def test_different_song_by_the_same_singer_scores_low() -> None:
    parts = score_candidate(
        song("晴天", ["周杰伦"], "叶惠美", 269),
        found("七里香", ["Jay Chou"], "七里香", 299),
        ALIASES,
    )
    assert status_for(parts.total) == "not_found"


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (269_000, 271_000, 1.0),
        (269_000, 281_000, 0.25),
        (269_000, 284_000, 0.0),
        (None, 1_000, 0.5),
    ],
)
def test_length_score(a: int | None, b: int, expected: float) -> None:
    assert length_score(a, b) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("total", "status"),
    [(0.8, "matched"), (0.79, "review"), (0.6, "review"), (0.59, "not_found")],
)
def test_status_for(total: float, status: str) -> None:
    assert status_for(total) == status
