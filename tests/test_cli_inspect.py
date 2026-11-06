import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from qq2spotify.cli import app
from qq2spotify.qq.playlist import ENDPOINTS

FIXTURE = Path(__file__).parent / "fixtures" / "qq_playlist_sample.json"
LINK = "https://y.qq.com/n/ryqq/playlist/7891234567"
runner = CliRunner()


def test_inspect_prints_the_songs(tmp_path: Path) -> None:
    raw_file = tmp_path / "raw.json"
    body = FIXTURE.read_text(encoding="utf-8")
    with respx.mock:
        respx.get(ENDPOINTS[0]).mock(return_value=httpx.Response(200, text=body))
        result = runner.invoke(app, ["inspect", LINK, "--save-raw", str(raw_file)])
    assert result.exit_code == 0, result.output
    assert "夜跑 & 晨练 (3 songs)" in result.output
    assert "晴天" in result.output
    assert "周杰伦" in result.output
    assert "4:29" in result.output
    assert "[Live]" in result.output  # square brackets aren't eaten as styling
    assert json.loads(raw_file.read_text(encoding="utf-8"))["code"] == 0


def test_inspect_sends_the_cookie_file(tmp_path: Path) -> None:
    cookie_file = tmp_path / "qq_cookie.txt"
    cookie_file.write_text("uin=123; qm_keyst=abc\n", encoding="utf-8")
    body = FIXTURE.read_text(encoding="utf-8")
    with respx.mock:
        route = respx.get(ENDPOINTS[0]).mock(
            return_value=httpx.Response(200, text=body)
        )
        result = runner.invoke(app, ["inspect", LINK, "--qq-cookie", str(cookie_file)])
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.headers["Cookie"] == "uin=123; qm_keyst=abc"


def test_inspect_explains_a_song_link() -> None:
    result = runner.invoke(
        app, ["inspect", "https://y.qq.com/n/ryqq/songDetail/001AbCdEfGhIjK"]
    )
    assert result.exit_code == 1
    assert "not a playlist link" in result.output


def test_inspect_explains_a_private_playlist() -> None:
    with respx.mock:
        for endpoint in ENDPOINTS:
            respx.get(endpoint).mock(
                return_value=httpx.Response(200, json={"code": -1})
            )
        result = runner.invoke(app, ["inspect", "7891234567"])
    assert result.exit_code == 1
    assert "private" in result.output
