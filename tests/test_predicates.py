from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from amontillado.grouping import Choice, Monitor
from amontillado.index import IndexedFile
from amontillado.metrics import Metrics
from amontillado.predicates import Judge, Predicate, PredicateError

PRIMARY_MONITOR = Monitor("DP-1", 21 / 9, "21:9")
SIDE = Monitor("HDMI-1", 16 / 9, "16:9")


def _file(record_id: str, lightness: float) -> IndexedFile:
    metrics = Metrics(lightness, 0.1, 0.5, None, None, 0.0, 0.0, 0.0, 0.0, (("#336699", 1.0),))
    return IndexedFile(
        Path(f"/l/{record_id}.png"), record_id, "sfw", False, True, 1600, 900, None, metrics
    )


PRIMARY = Choice(PRIMARY_MONITOR, _file("p", 0.4), 0.0)


def _record(record_id: str) -> dict[str, object]:
    return {"id": record_id, "name": f"n-{record_id}", "site": "wallhaven", "tags": ["a"]}


def _judge(tmp_path: Path, *commands: str) -> Judge:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    predicates = [Predicate(f"p{n}", cmd) for n, cmd in enumerate(commands)]
    return Judge(predicates, work, _record)


def test_exit_status_is_the_verdict(tmp_path: Path) -> None:
    judge = _judge(tmp_path, '[ "$AMO_MONITOR" = HDMI-1 ]')
    assert judge.accepts(PRIMARY, Choice(SIDE, _file("a", 0.3), 0.05))
    assert not judge.accepts(PRIMARY, Choice(Monitor("DP-2", 1.0, "1:1"), _file("a", 0.3), 0.05))


def test_every_predicate_must_accept_and_the_first_rejection_stops(tmp_path: Path) -> None:
    log = tmp_path / "log"
    judge = _judge(tmp_path, f"echo one >> {log}; exit 1", f"echo two >> {log}")
    assert not judge.accepts(PRIMARY, Choice(SIDE, _file("a", 0.3), 0.05))
    assert log.read_text() == "one\n"
    judge = _judge(tmp_path, "true", "true")
    assert judge.accepts(PRIMARY, Choice(SIDE, _file("a", 0.3), 0.05))


def test_verdicts_are_kept(tmp_path: Path) -> None:
    log = tmp_path / "log"
    judge = _judge(tmp_path, f"echo x >> {log}")
    candidate = Choice(SIDE, _file("a", 0.3), 0.05)
    assert judge.accepts(PRIMARY, candidate)
    assert judge.accepts(PRIMARY, candidate)
    assert log.read_text() == "x\n"


def test_what_a_predicate_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMO_WALLPAPER", "stale")
    out = tmp_path / "out"
    out.mkdir()
    judge = _judge(
        tmp_path,
        f'cp "$AMO_PRIMARY" {out}/p.json; cp "$AMO_CANDIDATE" {out}/c.json; '
        f'echo "${{AMO_WALLPAPER-unset}}" > {out}/env',
    )
    assert judge.accepts(PRIMARY, Choice(SIDE, _file("a", 0.3), 0.0512))
    primary = json.loads((out / "p.json").read_text())
    candidate = json.loads((out / "c.json").read_text())
    assert primary["record"] == _record("p")
    assert primary["monitor"] == {"name": "DP-1", "aspect": "21:9"}
    assert primary["distance"] == 0
    assert candidate["record"]["name"] == "n-a"
    assert candidate["file"]["path"] == "/l/a.png"
    assert candidate["file"]["width"] == 1600 and candidate["file"]["default"] is True
    assert candidate["file"]["metrics"]["lightness"] == 0.3
    assert candidate["file"]["metrics"]["palette"] == [["#336699", 1.0]]
    assert candidate["monitor"] == {"name": "HDMI-1", "aspect": "16:9"}
    assert candidate["distance"] == 0.051
    assert (out / "env").read_text() == "unset\n"


def test_output_goes_to_stderr(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    judge = _judge(tmp_path, "echo hello")
    assert judge.accepts(PRIMARY, Choice(SIDE, _file("a", 0.3), 0.05))
    captured = capfd.readouterr()
    assert captured.out == ""
    assert "hello" in captured.err


@pytest.mark.parametrize(
    ("cmd", "error"),
    [
        ("exit 2", "predicate p0 failed: exit status 2"),
        ("no-such-command-amo", "predicate p0 failed: exit status 127 (command not found)"),
        ("kill -TERM $$", "predicate p0 failed: killed by signal 15"),
    ],
)
def test_anything_but_0_or_1_is_an_error(tmp_path: Path, cmd: str, error: str) -> None:
    with pytest.raises(PredicateError, match=re.escape(error)):
        _judge(tmp_path, cmd).accepts(PRIMARY, Choice(SIDE, _file("a", 0.3), 0.05))


@pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")
def test_the_template_examples_work(tmp_path: Path) -> None:
    from amontillado.config_keys import PREDICATE_EXAMPLES

    examples = {example.name: example.cmd for example in PREDICATE_EXAMPLES}
    darker = Choice(SIDE, _file("a", 0.3), 0.05)
    lighter = Choice(SIDE, _file("b", 0.6), 0.05)
    assert _judge(tmp_path, examples["same-site"]).accepts(PRIMARY, darker)
    assert _judge(tmp_path, examples["no-lighter"]).accepts(PRIMARY, darker)
    assert not _judge(tmp_path, examples["no-lighter"]).accepts(PRIMARY, lighter)
    # busy is 0.0 in _file: calm everywhere.
    assert _judge(tmp_path, examples["calm-hdmi"]).accepts(PRIMARY, lighter)
