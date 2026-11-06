import json
from pathlib import Path

from qq2spotify.matching.search import Matcher, build_queries, load_aliases
from qq2spotify.models import SourceTrack


def song(
    title: str, artists: list[str], album: str | None = None, seconds: float = 0
) -> SourceTrack:
    return SourceTrack(
        0, title, tuple(artists), album, int(seconds * 1000) or None, "mid"
    )


def item(
    number: int,
    name: str,
    artists: list[str],
    album: str,
    seconds: float,
    **extra: object,
) -> dict:
    return {
        "uri": f"spotify:track:{number}",
        "name": name,
        "artists": [{"name": artist} for artist in artists],
        "album": {"name": album},
        "duration_ms": int(seconds * 1000),
        "external_urls": {"spotify": f"https://open.spotify.com/track/{number}"},
        **extra,
    }


class FakeApi:
    def __init__(self, answers: dict[str, list]) -> None:
        self.answers = answers
        self.queries: list[str] = []

    def get(self, path: str, params: dict) -> dict:
        assert path == "/search"
        assert params["type"] == "track"
        assert params["limit"] == 10
        self.queries.append(params["q"])
        return {"tracks": {"items": self.answers.get(params["q"], [])}}


def test_queries_try_spotify_names_first() -> None:
    assert build_queries(song("晴天 (Live)", ["周杰伦"]), {"周杰伦": ["Jay Chou"]}) == [
        "track:晴天 artist:Jay Chou",
        "track:晴天 artist:周杰伦",
        "晴天 Jay Chou",
        "track:晴天",
    ]


def test_queries_add_traditional_chinese() -> None:
    assert build_queries(song("后来的我们", ["五月天"]), {"五月天": ["Mayday"]}) == [
        "track:后来的我们 artist:Mayday",
        "track:後來的我們 artist:Mayday",
        "track:后来的我们 artist:五月天",
        "后来的我们 Mayday",
        "track:后来的我们",
    ]


def test_queries_for_mixed_names_use_both_halves() -> None:
    assert build_queries(song("喜欢你", ["G.E.M.邓紫棋"]), {}) == [
        "track:喜欢你 artist:G.E.M.",
        "track:喜歡你 artist:G.E.M.",
        "track:喜欢你 artist:邓紫棋",
        "喜欢你 G.E.M.",
        "track:喜欢你",
    ]


def test_queries_without_a_singer() -> None:
    assert build_queries(song("Rock & Roll [Live]", []), {}) == ["track:Rock & Roll"]


def test_stops_at_the_first_good_match() -> None:
    api = FakeApi(
        {"track:晴天 artist:Jay Chou": [item(1, "晴天", ["Jay Chou"], "葉惠美", 269.5)]}
    )
    result = Matcher(api, {"周杰伦": ["Jay Chou"]}).match(
        song("晴天", ["周杰伦"], "叶惠美", 269)
    )
    assert result.status == "matched"
    assert result.best is not None and result.best.uri == "spotify:track:1"
    assert result.searches == 1
    assert result.query == "track:晴天 artist:Jay Chou"
    assert api.queries == ["track:晴天 artist:Jay Chou"]


def test_keeps_the_best_result_across_searches() -> None:
    api = FakeApi(
        {
            "track:晴天 artist:周杰伦": [
                item(1, "晴天 - Live", ["周杰倫"], "演唱會", 280)
            ],
            "晴天 周杰伦": [item(2, "晴天", ["周杰倫"], "葉惠美", 269)],
        }
    )
    result = Matcher(api, {}).match(song("晴天", ["周杰伦"], "叶惠美", 269))
    assert result.status == "matched"
    assert result.best is not None and result.best.uri == "spotify:track:2"
    assert result.searches == 2


def test_nothing_found() -> None:
    api = FakeApi({})
    result = Matcher(api, {}).match(song("晴天", ["周杰伦"]))
    assert result.status == "not_found"
    assert result.best is None
    assert result.searches == len(api.queries) == 3


def test_skips_empty_local_and_unplayable_results() -> None:
    good = item(4, "晴天", ["周杰倫"], "葉惠美", 269)
    api = FakeApi(
        {
            "track:晴天 artist:周杰伦": [
                None,
                item(1, "晴天", ["周杰倫"], "葉惠美", 269, is_local=True),
                item(2, "晴天", ["周杰倫"], "葉惠美", 269, is_playable=False),
                good,
            ]
        }
    )
    result = Matcher(api, {}).match(song("晴天", ["周杰伦"], "叶惠美", 269))
    assert result.best is not None and result.best.uri == "spotify:track:4"


def test_pauses_between_searches() -> None:
    waits: list[float] = []
    matcher = Matcher(FakeApi({}), {}, pause=0.5, sleep=waits.append)
    matcher.match(song("晴天", ["周杰伦"]))  # 3 searches
    matcher.match(song("七里香", ["周杰伦"]))  # 3 more
    assert waits == [0.5] * 5


def test_bundled_aliases_and_the_users_own_file(tmp_path: Path) -> None:
    assert load_aliases()["周杰伦"] == ["Jay Chou"]
    assert load_aliases(tmp_path / "missing.json") == load_aliases()
    own = tmp_path / "aliases.json"
    own.write_text(
        json.dumps(
            {"周杰倫": "Jay Chou TW", "新歌手": ["New Singer"]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    merged = load_aliases(own)
    assert merged["周杰伦"] == ["Jay Chou TW"]  # Traditional key, user's file wins
    assert merged["新歌手"] == ["New Singer"]
