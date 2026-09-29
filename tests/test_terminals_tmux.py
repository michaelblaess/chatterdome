"""Agentenstart ohne Anzeige ueber tmux.

Aufgefallen am 15.09.2026: der Browser-Zugang laeuft auf senza als Dienst ohne
DISPLAY. "Agent starten" nahm automatisch gnome-terminal, und das scheiterte
still, weil es keinen Bildschirm gab.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chatterdome.kern import terminals
from chatterdome.tui import starter


def _linux(monkeypatch: pytest.MonkeyPatch, *, anzeige: bool, installiert: set[str]) -> None:
    monkeypatch.setattr(terminals.sys, "platform", "linux")
    monkeypatch.setattr(
        terminals.shutil, "which", lambda p: f"/usr/bin/{p}" if p in installiert else None
    )
    for name in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    if anzeige:
        monkeypatch.setenv("DISPLAY", ":1")


def test_ohne_anzeige_waehlt_automatisch_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, anzeige=False, installiert={"gnome-terminal", "tmux"})
    gefunden = terminals.finde("")
    assert gefunden is not None
    assert gefunden.schluessel == "tmux"


def test_gegenprobe_mit_anzeige_bleibt_es_beim_fenster(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, anzeige=True, installiert={"gnome-terminal", "tmux"})
    gefunden = terminals.finde("")
    assert gefunden is not None
    assert gefunden.schluessel == "gnome-terminal"


def test_ohne_anzeige_und_ohne_tmux_gibt_es_keins(monkeypatch: pytest.MonkeyPatch) -> None:
    # Lieber "kein Terminal gefunden" melden als ein Fenster starten, das nie aufgeht.
    _linux(monkeypatch, anzeige=False, installiert={"gnome-terminal"})
    assert terminals.finde("") is None


def test_nur_tmux_kommt_ohne_fenster_aus() -> None:
    ohne = [t.schluessel for t in terminals.TERMINALS if not t.fenster]
    assert ohne == ["tmux"]


def test_tmux_startet_eine_eigene_sitzung_im_hintergrund(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, anzeige=False, installiert={"tmux"})
    terminal = terminals.finde("tmux")
    assert terminal is not None
    datei = Path("/tmp/start.sh")
    zeile = starter._zeile(terminal, datei, "/home/michael")
    assert zeile[:4] == ["/usr/bin/tmux", "new-session", "-d", "-s"]
    assert zeile[4].startswith("agent-")
    assert zeile[5:] == ["-c", "/home/michael", "bash", "-lc", f"{datei}; exec bash"]
