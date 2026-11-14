"""The desktop's colour scheme as a variant (`variant: system`), with gdbus and gsettings faked."""

from __future__ import annotations

import subprocess

import pytest

from amontillado import desktop
from amontillado.desktop import GSETTINGS_COMMAND, PORTAL_COMMAND, desktop_variant

Reply = str | int | BaseException  # stdout, a non-zero exit status, or what run raises


def _fake(monkeypatch: pytest.MonkeyPatch, portal: Reply, gsettings: Reply) -> list[str]:
    """Answer the portal and gsettings commands; returns the tools run, in order."""
    replies = {PORTAL_COMMAND: portal, GSETTINGS_COMMAND: gsettings}
    calls: list[str] = []

    def run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command[0])
        reply = replies[tuple(command)]
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, int):
            return subprocess.CompletedProcess(command, reply, "", "Error: no bus\n")
        return subprocess.CompletedProcess(command, 0, reply, "")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    return calls


@pytest.mark.parametrize(
    ("reply", "variant"),
    [("(<<uint32 1>>,)\n", "dark"), ("(<<uint32 2>>,)\n", "light"), ("(<uint32 1>,)\n", "dark")],
)
def test_portal_decides(monkeypatch: pytest.MonkeyPatch, reply: str, variant: str) -> None:
    calls = _fake(monkeypatch, reply, "'prefer-light'\n")
    assert desktop_variant() == variant
    assert calls == ["gdbus"]


@pytest.mark.parametrize(
    "portal", ["(<<uint32 0>>,)\n", 1, FileNotFoundError(), subprocess.TimeoutExpired("gdbus", 5)]
)
@pytest.mark.parametrize(
    ("reply", "variant"), [("'prefer-dark'\n", "dark"), ("'prefer-light'\n", "light")]
)
def test_gsettings_without_the_portal(
    monkeypatch: pytest.MonkeyPatch, portal: Reply, reply: str, variant: str
) -> None:
    calls = _fake(monkeypatch, portal, reply)
    assert desktop_variant() == variant
    assert calls == ["gdbus", "gsettings"]


@pytest.mark.parametrize(
    ("portal", "gsettings", "why"),
    [
        ("(<<uint32 0>>,)\n", "'default'\n", "portal: no preference; gsettings: no preference"),
        (FileNotFoundError(), FileNotFoundError(), "gdbus not found; gsettings: gsettings not"),
        (1, 1, "portal: Error: no bus; gsettings: Error: no bus"),
        ("garbage", "'sepia'\n", "unexpected reply 'garbage'; gsettings: unknown value 'sepia'"),
    ],
)
def test_no_scheme_is_auto_with_a_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    portal: Reply,
    gsettings: Reply,
    why: str,
) -> None:
    _fake(monkeypatch, portal, gsettings)
    assert desktop_variant() == "auto"
    assert why in caplog.text
    assert "using auto" in caplog.text
