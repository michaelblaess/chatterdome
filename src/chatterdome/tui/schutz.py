"""Fremdtext fuer Ziele entschaerfen, die Markup auswerten.

Fremdtext ist alles, was nicht aus den Sprachdateien stammt: der letzte Prompt
einer Sitzung, ein Ordnerpfad, eine Bus-Nachricht, die Fehlerausgabe eines
Unterprozesses. Eine eckige Klammer darin ist fuer rich keine Klammer, sondern
ein Auszeichnungsbefehl - ``[/usage-Screenshot]`` schliesst ein Element, das nie
geoeffnet wurde, und rich wirft einen ``MarkupError``.

Am 12.08.2026 hat genau das die Oberflaeche umgebracht: der Text stand als
letzter Prompt in der Agententabelle, der Fehler fiel erst beim Neuberechnen der
Inhaltshoehe auf (also beim Ziehen einer Trennlinie), und der Fehlerdialog von
textual-widgets ist am selben Text ein zweites Mal gestorben.

Der Schutz gehoert deshalb an den Kanal - an die eine Stelle, durch die der
Fremdtext ins Widget geht - und nicht an jedes einzelne Feld. Feld fuer Feld war
der Zustand davor, und dabei blieben vier Stellen unbemerkt offen.
"""

from __future__ import annotations

from rich.markup import escape


def klartext(text: str) -> str:
    """Gibt den Text so zurueck, dass Markup-Ziele ihn woertlich anzeigen."""
    return escape(text)


def klartext_oder_nichts(text: str | None) -> str | None:
    """Wie ``klartext``, laesst ``None`` aber durch.

    Ein Hinweisfeld erwartet ``None``, wenn es nichts anzuzeigen gibt - ein
    leerer Text ergaebe stattdessen ein leeres Kaestchen am Mauszeiger.
    """
    return None if text is None else escape(text)
