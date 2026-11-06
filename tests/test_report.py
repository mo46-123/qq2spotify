import codecs
import csv
from pathlib import Path

from qq2spotify.models import Candidate, MatchResult, ScoreParts, SourceTrack
from qq2spotify.report import COLUMNS, count_statuses, write_report

SUNNY = SourceTrack(0, "晴天", ("周杰伦",), "叶惠美", 269_000, "mid1")
ROCK = SourceTrack(1, "Rock & Roll [Live]", (), None, None, "mid2")
FOUND = Candidate(
    "spotify:track:1",
    "晴天",
    ("Jay Chou",),
    "葉惠美",
    269_500,
    "https://open.spotify.com/track/1",
)


def test_report_has_a_row_per_song_and_opens_in_excel(tmp_path: Path) -> None:
    matched = MatchResult(
        source=SUNNY,
        status="matched",
        best=FOUND,
        parts=ScoreParts(1.0, 1.0, 1.0, 1.0, 0.0, 1.0),
        query="track:晴天 artist:Jay Chou",
        searches=1,
    )
    missing = MatchResult(source=ROCK, status="not_found", searches=1)
    path = tmp_path / "report.csv"
    write_report(path, [matched, missing])

    assert path.read_bytes().startswith(codecs.BOM_UTF8)  # Excel needs this
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert list(rows[0]) == list(COLUMNS)
    assert rows[0]["position"] == "1"
    assert rows[0]["qq_length"] == "4:29"
    assert rows[0]["status"] == "matched"
    assert rows[0]["score"] == "1.00"
    assert rows[0]["spotify_artists"] == "Jay Chou"
    assert rows[0]["artist_by_search"] == ""
    assert rows[0]["spotify_url"] == "https://open.spotify.com/track/1"
    assert rows[1]["status"] == "not_found"
    assert rows[1]["spotify_title"] == ""
    assert rows[1]["score"] == "0.00"
    assert count_statuses([matched, missing]) == {"matched": 1, "not_found": 1}
