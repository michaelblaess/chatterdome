"""Gemeinsames Test-Setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from chatterdome import i18n
from chatterdome.kern import absturz
from chatterdome.kern import einstellungen as einstellungen_modul


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
    # Auch der Ordner von vor der Umbenennung - sonst kopierte ein Startpunkt im
    # Test die echten Daten.
    monkeypatch.setattr(einstellungen_modul, "ALTES_VERZEICHNIS", tmp_path / "alt")
    # Und das Absturzprotokoll: sein Pfad entsteht beim Import aus dem echten
    # Home. Ein Testlauf am 29.09.2026 hat so ein fault.log in ~/.chatterdome
    # hinterlassen - vorher landeten solche Zeilen in ~/.claude-sanctuary.
    monkeypatch.setattr(absturz, "PROTOKOLL", tmp_path / "fault.log")
    return datei
