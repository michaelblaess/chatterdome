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

VERZEICHNIS = Path.home() / ".chatterdome"
DATEI = VERZEICHNIS / "settings.json"
ZUSTIMMUNG = VERZEICHNIS / "disclaimer.json"

ALTES_VERZEICHNIS = Path.home() / ".claude-sanctuary"
"""Der Ordner vor der Umbenennung in Chatterdome am 29.09.2026."""


UEBERNOMMEN = ".uebernommen-aus-claude-sanctuary"
"""Markierung im neuen Ordner: die Uebernahme ist gelaufen und laeuft nie wieder."""


def alten_ordner_uebernehmen(alt: Path | None = None, neu: Path | None = None) -> bool:
    """Kopiert, was vom Ordner vor der Umbenennung im neuen noch fehlt. Einmalig.

    Kopieren statt verschieben: ein noch laufendes Programm alten Namens haelt
    unter Windows seine Datenbanken offen, ein Verschieben scheiterte dann
    mittendrin. Der alte Ordner bleibt liegen und kann spaeter von Hand weg.

    Eintragsweise und nicht "nur wenn der neue Ordner fehlt": das
    Absturzprotokoll legt den Ordner schon an, bevor ein Startpunkt hierher
    kommt. Am 29.09.2026 hat genau das die erste Fassung ausgehebelt - es
    stand nur ein ``fault.log`` darin, und die Uebernahme hielt den Ordner
    fuer eingerichtet. Vorhandenes im neuen Ordner wird nie ueberschrieben.

    Aufgerufen aus den Startpunkten, nicht beim Import - sonst fassten schon
    die Tests das echte Home an.

    :returns: True, wenn diesmal uebernommen wurde.
    """
    import shutil
    from datetime import datetime

    alt = alt if alt is not None else ALTES_VERZEICHNIS
    neu = neu if neu is not None else VERZEICHNIS
    marke = neu / UEBERNOMMEN
    if marke.exists() or not alt.is_dir():
        return False
    neu.mkdir(parents=True, exist_ok=True)
    for eintrag in alt.iterdir():
        ziel = neu / eintrag.name
        if ziel.exists():
            continue
        if eintrag.is_dir():
            shutil.copytree(eintrag, ziel)
        else:
            shutil.copy2(eintrag, ziel)
    marke.write_text(f"{datetime.now().isoformat(timespec='seconds')} aus {alt}\n",
                     encoding="utf-8")
    return True

VORGABEN: dict[str, Any] = {
    "language": "de",
    "theme": "textual-dark",
    # Mesh ist die Vorgabe: wer mehrere Rechner betreibt, will sie auch sehen.
    "nur_lokal": False,
    "aktualisierung_sekunden": 5,
    "proxy_url": "",
    "log_sichtbar": True,
    "id_spalte": False,
    # Neues Terminal. "auto" heisst: das erste vorhandene nehmen.
    "terminal": "auto",
    # Befehle, die im neuen Terminal VOR Claude laufen - eine je Zeile.
    "terminal_vorbereitung": "",
    # Optionaler Pfad zu einem Skript, das vor diesen Zeilen ausgefuehrt wird.
    "terminal_skript": "",
    # Wie Claude Code auf einem Agenten-Rechner aktualisiert wird.
    "update_verfahren": "claude",
    # Verzeichnis der Gedaechtnisnotizen. Leer heisst ~/.claude/memory. Wer
    # je Projekt ein eigenes Verzeichnis fuehrt, traegt es hier ein.
    "gedaechtnis_pfad": "",
    # Tastenbelegung. Leer heisst: nach Betriebssystem (macOS klassisch, sonst
    # F-Tasten). Die Tabellen dazu stehen in tui/keymap.py.
    "keymap_style": "",
    "keymap_vim": False,
    # Eigene Belegungen, Aktion auf Tastenliste, etwa {"toggle_log": ["alt+l"]}.
    "keymap_custom": {},
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
        # newline="\n": sonst schreibt Windows CRLF in die JSON-Datei.
        self._datei.write_text(
            json.dumps(werte, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
