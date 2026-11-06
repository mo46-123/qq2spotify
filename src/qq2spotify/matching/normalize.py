"""Clean up song titles and artist names so QQ Music and Spotify can be compared."""

import html
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from qq2spotify.matching.chinese import to_simplified

# Extras in brackets: (Live), （伴奏）, [Remix], 【DJ版】.
BRACKETS_RE = re.compile(r"[(（\[【]([^)）\]】]*)[)）\]】]")
# Spotify often puts the version after a dash: "Song - Live".
DASH_RE = re.compile(r"\s+[-–—]\s+")
FEATURING_RE = re.compile(
    r"^\s*(?:feat\.?|ft\.?|featuring|with)\s+(.+)$", re.IGNORECASE
)
ARTIST_SPLIT_RE = re.compile(r"\s*(?:,|，|&|/|、|\band\b)\s*", re.IGNORECASE)
# Chinese characters only, and any East Asian script (Chinese, Japanese, Korean).
CJK_RE = re.compile(r"[㐀-鿿豈-﫿]+")
EAST_ASIAN_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯豈-﫿]")
LATIN_RE = re.compile(r"[A-Za-z]")
NAME_BRACKETS_RE = re.compile(r"[(（]([^)）]*)[)）]")
PUNCTUATION_RE = re.compile(r"[\W_]+")
# Concert albums, such as "2004無與倫比演唱會 (Live)".
LIVE_ALBUM_RE = re.compile(r"(?<![a-z0-9])live(?![a-z0-9])|演唱会|现场")

# Words that mark a different version of a song, and the tag they stand for.
VERSION_WORDS = {
    "live": "live",
    "现场": "live",
    "演唱会": "live",
    "remix": "remix",
    "demo": "demo",
    "instrumental": "instrumental",
    "off vocal": "instrumental",
    "伴奏": "instrumental",
    "纯音乐": "instrumental",
    "karaoke": "karaoke",
    "ktv": "karaoke",
    "cover": "cover",
    "翻唱": "cover",
    "翻自": "cover",
    "dj": "dj",
    "acoustic": "acoustic",
    "女版": "female",
    "女声版": "female",
    "男版": "male",
    "男声版": "male",
    "sped up": "sped up",
    "加速版": "sped up",
    "slowed": "slowed",
    "慢速版": "slowed",
}
# English words only count as whole words ("live", not "olive").
_WORD_PATTERNS = {
    word: re.compile(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])")
    for word in VERSION_WORDS
    if word.isascii()
}


def _nfkc(text: str | None) -> str:
    # NFKC turns full-width letters, digits and brackets into normal ones.
    return unicodedata.normalize("NFKC", html.unescape(text or "")).strip()


@lru_cache(maxsize=16384)
def clean(text: str | None) -> str:
    """Lower-case, Simplified Chinese, no punctuation or spaces. For comparing only."""
    return PUNCTUATION_RE.sub("", to_simplified(_nfkc(text)).lower())


def _version_tags(extra: str) -> set[str]:
    lowered = to_simplified(extra.lower())
    tags = set()
    for word, tag in VERSION_WORDS.items():
        pattern = _WORD_PATTERNS.get(word)
        found = bool(pattern.search(lowered)) if pattern else word in lowered
        if found:
            tags.add(tag)
    return tags


@dataclass(frozen=True)
class TitleParts:
    core: str  # the title without extras, as written
    tags: frozenset[str]  # version tags such as "live" or "instrumental"
    featured: tuple[str, ...]  # artists named with feat./with


@lru_cache(maxsize=16384)
def split_title(title: str) -> TitleParts:
    """Split "晴天 (Live)" into the core title "晴天" and the version tag "live"."""
    text = _nfkc(title)
    extras = BRACKETS_RE.findall(text)
    core = BRACKETS_RE.sub(" ", text)
    pieces = DASH_RE.split(core, maxsplit=1)
    if len(pieces) == 2 and pieces[0].strip():
        core = pieces[0]
        extras.append(pieces[1])
    tags: set[str] = set()
    featured: list[str] = []
    for extra in extras:
        named = FEATURING_RE.match(extra)
        if named:
            featured.extend(
                name for name in ARTIST_SPLIT_RE.split(named.group(1)) if name.strip()
            )
        else:
            tags |= _version_tags(extra)
    core = " ".join(core.split()) or text
    return TitleParts(core=core, tags=frozenset(tags), featured=tuple(featured))


@lru_cache(maxsize=16384)
def album_tags(album: str | None) -> frozenset[str]:
    """{"live"} for a concert album, otherwise nothing."""
    lowered = to_simplified(_nfkc(album).lower())
    return frozenset({"live"}) if LIVE_ALBUM_RE.search(lowered) else frozenset()


def _halves(name: str) -> tuple[str, str]:
    """Split a name like "G.E.M.邓紫棋" into its Latin and Chinese halves."""
    chinese = "".join(CJK_RE.findall(name))
    latin = " ".join(CJK_RE.sub(" ", name).split())
    return latin, chinese


@lru_cache(maxsize=16384)
def name_parts(name: str) -> tuple[str, ...]:
    """The separate spellings inside one artist name.

    "G.E.M.邓紫棋" gives ("G.E.M.", "邓紫棋"), "辉星 (휘성)" gives ("辉星", "휘성"),
    and "周杰伦" gives ("周杰伦",).
    """
    text = _nfkc(name)
    pieces = [NAME_BRACKETS_RE.sub(" ", text), *NAME_BRACKETS_RE.findall(text)]
    parts: list[str] = []
    for piece in pieces:
        tidy = " ".join(piece.split())
        if not tidy:
            continue
        latin, chinese = _halves(tidy)
        if chinese and LATIN_RE.search(latin):
            parts += [latin, chinese]
        else:
            parts.append(tidy)
    return tuple(dict.fromkeys(parts))


@lru_cache(maxsize=16384)
def name_variants(name: str) -> frozenset[str]:
    """Cleaned forms of an artist name: the whole name and each of its parts."""
    variants = {clean(name), *(clean(part) for part in name_parts(name))}
    variants.discard("")
    return frozenset(variants)


def search_names(name: str) -> list[str]:
    """Names worth searching Spotify with: each separate spelling in the name."""
    return list(name_parts(name))


def is_latin_name(name: str) -> bool:
    """True for names written only in Latin letters, like "Sam Lee"."""
    return bool(LATIN_RE.search(name)) and not EAST_ASIAN_RE.search(name)


def is_east_asian_name(name: str) -> bool:
    """True for names written only in Chinese, Japanese or Korean, like "李圣杰"."""
    return bool(EAST_ASIAN_RE.search(name)) and not LATIN_RE.search(name)
