"""Convert between Simplified and Traditional Chinese with OpenCC."""

from functools import cache, lru_cache

from opencc import OpenCC


@cache
def _converter(config: str) -> OpenCC:
    return OpenCC(config)


@lru_cache(maxsize=8192)
def to_simplified(text: str) -> str:
    return _converter("t2s").convert(text)


@lru_cache(maxsize=8192)
def to_taiwan(text: str) -> str:
    """Traditional Chinese as written in Taiwan."""
    return _converter("s2tw").convert(text)


@lru_cache(maxsize=8192)
def to_hongkong(text: str) -> str:
    """Traditional Chinese as written in Hong Kong."""
    return _converter("s2hk").convert(text)
