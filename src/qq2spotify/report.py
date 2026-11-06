"""Save match results as a CSV file that opens in Excel."""

import csv
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from qq2spotify.models import MatchResult

COLUMNS = (
    "position",
    "qq_title",
    "qq_artists",
    "qq_album",
    "qq_length",
    "status",
    "score",
    "title_score",
    "artist_score",
    "length_score",
    "album_score",
    "artist_by_search",
    "spotify_title",
    "spotify_artists",
    "spotify_album",
    "spotify_length",
    "spotify_url",
    "query",
    "searches",
)


def format_length(duration_ms: int | None) -> str:
    if not duration_ms:
        return ""
    seconds = duration_ms // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def report_row(result: MatchResult) -> list[object]:
    track, best, parts = result.source, result.best, result.parts
    row: list[object] = [
        track.position + 1,
        track.title,
        " / ".join(track.artists),
        track.album or "",
        format_length(track.duration_ms),
        result.status,
        f"{result.score:.2f}",
    ]
    if parts:
        row += [f"{parts.title:.2f}", f"{parts.artist:.2f}"]
        row += [f"{parts.length:.2f}", f"{parts.album:.2f}"]
        row += ["yes" if parts.artist_by_search else ""]
    else:
        row += ["", "", "", "", ""]
    if best:
        row += [best.title, " / ".join(best.artists), best.album]
        row += [format_length(best.duration_ms), best.url]
    else:
        row += ["", "", "", "", ""]
    row += [result.query or "", result.searches]
    return row


def write_report(path: Path, results: Iterable[MatchResult]) -> None:
    # utf-8-sig adds a byte-order mark, which Excel needs to show Chinese properly.
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(COLUMNS)
        writer.writerows(report_row(result) for result in results)


def count_statuses(results: Iterable[MatchResult]) -> Counter[str]:
    return Counter(result.status for result in results)
