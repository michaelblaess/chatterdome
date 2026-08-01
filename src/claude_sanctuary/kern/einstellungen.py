"""Einstellungen als schlichtes JSON-Dokument.

Bewusst ein reines ``dict`` und kein typisiertes Zwischenmodell: die
Bruecke dict-zu-Dataclass verlangt, dass jedes Feld an drei Stellen gepflegt
wird, und genau dort sind schon mehrfach Einstellungen nach dem Speichern
zurueckgesprungen. Hier wandert das volle Dokument durch den Dialog und wird
per Merge zurueckgeschrieben - dann kann kein Feld durchrutschen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERZEICHNIS = Path.home() / ".claude-sanctuary"
DATEI = VERZEICHNIS / "settings.json"
ZUSTIMMUNG = VERZEICHNIS / "disclaimer.json"

VORGABEN: dict[str, Any] = {
    "language": "de",
    "theme": "textual-dark",
    "nur_lokal": True,
    "aktualisierung_sekunden": 5,
    "proxy_url": "",
    "log_sichtbar": True,
    "id_spalte": False,
}


class Einstellungen:
    """Laedt und speichert das Einstellungsdokument."""

    def __init__(self, datei: Path | None = None) -> None:
        self._datei = datei if datei is not None else DATEI

    @property
    def datei(self) -> Path:
        return self._datei

    def laden(self) -> dict[str, Any]:
        """Liest die Datei und ergaenzt fehlende Schluessel mit den Vorgaben."""
        werte: dict[str, Any] = dict(VORGABEN)
        try:
            roh = json.loads(self._datei.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return werte
        if isinstance(roh, dict):
            werte.update(roh)
        return werte

    def speichern(self, aenderungen: dict[str, Any]) -> None:
        """Schreibt die Aenderungen ueber den vorhandenen Stand."""
        werte = self.laden()
        werte.update(aenderungen)
        self._datei.parent.mkdir(parents=True, exist_ok=True)
        self._datei.write_text(
            json.dumps(werte, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
