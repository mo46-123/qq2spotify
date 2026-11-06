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


# The cases below come from a real 109-song playlist run.

SAM_LEE_SONG = song("你那么爱她", ["李圣杰"], "音乐十年李圣杰, 唯一精选", 257)
SAM_LEE_FOUND = found("你那麼愛她", ["Sam Lee"], "音樂十年李聖傑, 唯一精選", 257)


def test_spotify_search_can_confirm_an_english_artist_name() -> None:
    parts = score_candidate(SAM_LEE_SONG, SAM_LEE_FOUND, {}, artist_filter="李圣杰")
    assert parts.artist_by_search
    assert parts.artist == 0.85
    assert status_for(parts.total) == "matched"


def test_no_confirmation_without_an_artist_filter() -> None:
    parts = score_candidate(SAM_LEE_SONG, SAM_LEE_FOUND, {})
    assert not parts.artist_by_search
    assert status_for(parts.total) == "review"


def test_no_confirmation_when_the_length_is_far_off() -> None:
    longer = found("你那麼愛她", ["Sam Lee"], "音樂十年李聖傑, 唯一精選", 280)
    parts = score_candidate(SAM_LEE_SONG, longer, {}, artist_filter="李圣杰")
    assert not parts.artist_by_search


def test_chinese_named_cover_gets_no_confirmation() -> None:
    # Searching artist:王杰 returned a cover by 王者桑杰; both are Chinese names,
    # so they are compared directly instead.
    parts = score_candidate(
        song("我是真的爱上你", ["王杰"], "爱与梦", 302),
        found("我是真的爱上你", ["王者桑杰"], "我是真的爱上你", 234),
        {},
        artist_filter="王杰",
    )
    assert not parts.artist_by_search
    assert status_for(parts.total) == "review"


def test_concert_album_counts_as_a_live_version() -> None:
    parts = score_candidate(
        song("不能说的秘密", ["周杰伦"], "SONYBMG华语音乐快递10", 296),
        found("不能說的秘密", ["Jay Chou"], "周杰倫2007世界巡迴演唱會", 297),
        ALIASES,
    )
    assert parts.penalty == 0.3
    assert parts.total < MATCHED


def test_live_on_both_sides_is_fine() -> None:
    parts = score_candidate(
        song("倒带 (Live)", ["周杰伦"], "周杰伦 2004 无与伦比 演唱会 Live CD", 276),
        found("倒帶 - Live", ["Jay Chou"], "2004無與倫比演唱會 (Live)", 276),
        ALIASES,
    )
    assert parts.penalty == 0.0
    assert status_for(parts.total) == "matched"


def test_female_cover_is_a_different_version() -> None:
    parts = score_candidate(
        song("爱就一个字", ["张信哲"], "宝莲灯 电影原声音乐", 275),
        found("爱就一个字 - 女声版", ["傲七爷"], "爱就一个字 (女声版)", 271),
        {},
    )
    assert parts.penalty == 0.3
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
