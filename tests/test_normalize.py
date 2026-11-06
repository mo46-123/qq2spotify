import pytest

from qq2spotify.matching.chinese import to_hongkong, to_simplified, to_taiwan
from qq2spotify.matching.normalize import (
    album_tags,
    clean,
    is_east_asian_name,
    is_latin_name,
    name_variants,
    search_names,
    split_title,
)


def test_chinese_conversion() -> None:
    assert to_simplified("後來的我們") == "后来的我们"
    assert to_taiwan("后来的我们") == "後來的我們"
    assert to_hongkong("后来的我们") != "后来的我们"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ｈｅｌｌｏ，　Ｗｏｒｌｄ！", "helloworld"),
        ("後來的我們", "后来的我们"),
        ("G.E.M. 鄧紫棋", "gem邓紫棋"),
        ("Rock &amp; Roll", "rockroll"),
        ("", ""),
    ],
)
def test_clean(text: str, expected: str) -> None:
    assert clean(text) == expected


@pytest.mark.parametrize(
    ("title", "core", "tags", "featured"),
    [
        ("晴天 (Live)", "晴天", {"live"}, ()),
        ("晴天 - Live", "晴天", {"live"}, ()),
        ("Mojito (伴奏)", "Mojito", {"instrumental"}, ()),
        ("说好不哭（with 五月天阿信）", "说好不哭", set(), ("五月天阿信",)),
        (
            "Wake Me Up (feat. Aloe Blacc & Avicii)",
            "Wake Me Up",
            set(),
            ("Aloe Blacc", "Avicii"),
        ),
        ("孤勇者 (《英雄联盟：双城之战》动画剧集中文主题曲)", "孤勇者", set(), ()),
        ("Yesterday - Remastered 2009", "Yesterday", set(), ()),
        ("爱情转移 【DJ版】", "爱情转移", {"dj"}, ()),
        ("Olive (Remix)", "Olive", {"remix"}, ()),
        ("小情歌 (苏打绿版)", "小情歌", set(), ()),
        ("爱就一个字 - 女声版", "爱就一个字", {"female"}, ()),
        ("(Intro)", "(Intro)", set(), ()),
    ],
)
def test_split_title(
    title: str, core: str, tags: set[str], featured: tuple[str, ...]
) -> None:
    parts = split_title(title)
    assert parts.core == core
    assert parts.tags == tags
    assert parts.featured == featured


@pytest.mark.parametrize(
    ("name", "variants"),
    [
        ("G.E.M.邓紫棋", {"gem邓紫棋", "gem", "邓紫棋"}),
        ("Suki刘舒妤", {"suki刘舒妤", "suki", "刘舒妤"}),
        ("周杰倫", {"周杰伦"}),
        ("Jay Chou", {"jaychou"}),
        ("辉星 (휘성)", {"辉星휘성", "辉星", "휘성"}),
    ],
)
def test_name_variants(name: str, variants: set[str]) -> None:
    assert name_variants(name) == variants


@pytest.mark.parametrize(
    ("name", "names"),
    [
        ("G.E.M.邓紫棋", ["G.E.M.", "邓紫棋"]),
        ("辉星 (휘성)", ["辉星", "휘성"]),
        ("周杰伦", ["周杰伦"]),
        ("", []),
    ],
)
def test_search_names(name: str, names: list[str]) -> None:
    assert search_names(name) == names


@pytest.mark.parametrize(
    ("album", "tags"),
    [
        ("2004無與倫比演唱會 (Live)", {"live"}),
        ("我是歌手第三季 (第六期 Live)", {"live"}),
        ("周杰倫2007世界巡迴演唱會", {"live"}),
        ("SONYBMG华语音乐快递10", set()),
        ("Olive Tree", set()),
        (None, set()),
    ],
)
def test_album_tags(album: str | None, tags: set[str]) -> None:
    assert album_tags(album) == tags


@pytest.mark.parametrize(
    ("name", "latin", "east_asian"),
    [
        ("Sam Lee", True, False),
        ("李圣杰", False, True),
        ("휘성", False, True),
        ("G.E.M.邓紫棋", False, False),
    ],
)
def test_script_checks(name: str, latin: bool, east_asian: bool) -> None:
    assert is_latin_name(name) is latin
    assert is_east_asian_name(name) is east_asian
