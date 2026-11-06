import pytest

from qq2spotify.matching.chinese import to_hongkong, to_simplified, to_taiwan
from qq2spotify.matching.normalize import (
    clean,
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
    ],
)
def test_name_variants(name: str, variants: set[str]) -> None:
    assert name_variants(name) == variants


@pytest.mark.parametrize(
    ("name", "names"),
    [("G.E.M.邓紫棋", ["G.E.M.", "邓紫棋"]), ("周杰伦", ["周杰伦"]), ("", [])],
)
def test_search_names(name: str, names: list[str]) -> None:
    assert search_names(name) == names
