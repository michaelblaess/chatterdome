"""Der Starter darf die Marker der startenden Claude-Sitzung nicht vererben (28.09.2026)."""

from __future__ import annotations

import pytest

from chatterdome.tui.starter import saubere_umgebung


def test_sitzungsmarker_fallen_weg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "\\\\.\\pipe\\fremd")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_PID", "4711")
    umgebung = {k.upper() for k in saubere_umgebung()}
    assert "CLAUDE_CODE_CHILD_SESSION" not in umgebung
    assert "CLAUDE_CODE_MESSAGING_SOCKET" not in umgebung
    assert "CLAUDECODE" not in umgebung
    assert "CLAUDE_PID" not in umgebung


def test_alles_andere_bleibt(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proxy und eigene Variablen braucht der neue Agent weiterhin.
    monkeypatch.setenv("HTTPS_PROXY", "http://p:8080")
    monkeypatch.setenv("CLAUDE_INSTANZ_NAME", "Marga")
    umgebung = saubere_umgebung()
    assert umgebung["HTTPS_PROXY"] == "http://p:8080"
    assert umgebung["CLAUDE_INSTANZ_NAME"] == "Marga"


def test_pfad_zur_binaerdatei_bleibt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "C:/claude.exe")
    assert saubere_umgebung()["CLAUDE_CODE_EXECPATH"] == "C:/claude.exe"
