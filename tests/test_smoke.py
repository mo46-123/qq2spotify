import re

import pytest

import qq2spotify


def test_version_looks_like_x_y_z() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", qq2spotify.__version__)


def test_cli_prints_version() -> None:
    pytest.importorskip("typer")
    from typer.testing import CliRunner

    from qq2spotify.cli import app

    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == qq2spotify.__version__
