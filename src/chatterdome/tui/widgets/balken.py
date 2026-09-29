"""Ein Balken aus Textzeichen.

Bewusst ein eigenes Modul statt zweier Kopien: die Funktion stand zuerst nur
im Gedaechtnis-Panel, und der Statistik-Tab braucht genau dieselbe. Zwei
Fassungen laufen frueher oder spaeter auseinander - im Namenspool des Bus ist
das schon einmal passiert.

Warum ueberhaupt Text und kein Diagramm: bei wenigen Eintraegen verteilt
plotext die Balken auf mehr Zeilen, als es Eintraege gibt, und schreibt die
Beschriftung nur an eine davon. Sechs Ordner auf zwoelf Zeilen sehen dann aus
wie zwoelf Balken, von denen sechs leer sind. Eine Zeile je Eintrag hat dieses
Problem nicht.
"""

from __future__ import annotations

BALKEN_BREITE = 34
"""Zellen fuer den laengsten Balken. Passt neben die Beschriftung."""


def balken(anteil: float, breite: int = BALKEN_BREITE) -> str:
    """Zeichnet einen Balken. Ein Wert ueber null bekommt immer ein Zeichen.

    Sonst verschwindet der kleinere von zwei Werten ganz, und ein Balken der
    Laenge null sieht aus wie "kostet nichts" statt "kostet wenig".
    """
    voll = round(max(0.0, min(1.0, anteil)) * breite)
    if anteil > 0:
        voll = max(1, voll)
    return "█" * voll + "░" * (breite - voll)
