"""Schnittstellen des Kerns.

Die Oberflaechen kennen ausschliesslich diese Protokolle, nie eine konkrete
Quelle. Damit laesst sich die heutige Anbindung ueber den Kurzbefehl spaeter
gegen eine HTTP-Anbindung tauschen, ohne dass TUI oder Web davon erfahren.
"""

from __future__ import annotations

from typing import Protocol

from claude_sanctuary.kern.modelle import Auftrag, Bestand


class Quelle(Protocol):
    """Liefert den Zustand der Agenten und nimmt Auftraege entgegen."""

    def bestand(self, *, mesh: bool = False) -> Bestand:
        """Alle sichtbaren Agenten.

        :param mesh: auch die anderen Rechner im Tailnet abfragen.
        """
        ...

    def verlauf(self, name: str) -> list[Auftrag]:
        """Auftraege und Quittungen mit einem bestimmten Agenten."""
        ...

    def senden(self, an: str, text: str, *, topic: str = "", quittung: bool = False) -> str:
        """Legt einen Auftrag ab.

        :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
        """
        ...

    def stoppen(self, name: str) -> str:
        """Beendet eine Sitzung.

        :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
        """
        ...
