"""Gemeinsames Test-Setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_sanctuary import i18n
from claude_sanctuary.kern import einstellungen as einstellungen_modul


@pytest.fixture(autouse=True)
def _deutsch() -> None:
    """Ohne geladene Sprache liefert t() den Schluessel statt des Textes."""
    i18n.load_locale("de")


@pytest.fixture(autouse=True)
def _eigene_einstellungen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Verlegt die Einstellungen, damit Tests nie die echte Datei anfassen."""
    datei = tmp_path / "settings.json"
    monkeypatch.setattr(einstellungen_modul, "VERZEICHNIS", tmp_path)
    monkeypatch.setattr(einstellungen_modul, "DATEI", datei)
    monkeypatch.setattr(einstellungen_modul, "ZUSTIMMUNG", tmp_path / "disclaimer.json")
    return datei
