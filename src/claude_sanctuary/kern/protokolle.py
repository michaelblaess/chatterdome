"""Schnittstellen des Kerns.

Die Oberflaechen kennen ausschliesslich diese Protokolle, nie eine konkrete
Quelle. Damit laesst sich die heutige Anbindung ueber den Kurzbefehl spaeter
gegen eine HTTP-Anbindung tauschen, ohne dass TUI oder Web davon erfahren.
"""

from __future__ import annotations

from typing import Protocol

from claude_sanctuary.kern.modelle import Auftrag, Bestand, Busbestand, Namenspool


class Quelle(Protocol):
    """Liefert den Zustand der Agenten und nimmt Auftraege entgegen."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        """Alle sichtbaren Agenten.

        :param mesh: auch die anderen Rechner im Tailnet abfragen.
        :param tokens: zusaetzlich den Verbrauch ermitteln (langsam).
        """
        ...

    def namen(self) -> Namenspool:
        """Aktives Namensmotiv und freie Namen."""
        ...

    def verlauf(self, name: str) -> list[Auftrag]:
        """Auftraege und Quittungen mit einem bestimmten Agenten."""
        ...

    def bestandsverlauf(self, grenze: int = 0) -> Busbestand:
        """Der gesamte Bus, nicht auf einen Agenten eingeschraenkt.

        :param grenze: hoechstens so viele Auftraege, die neuesten. 0 heisst alle.
        """
        ...

    def senden(
        self,
        an: str,
        text: str,
        *,
        topic: str = "",
        quittung: bool = False,
        host: str = "",
        von: str = "",
    ) -> str:
        """Legt einen Auftrag ab.

        :param host: Rechner des Empfaengers - spart die Mesh-Suche.
        :param von: Absendername, wenn kein Sitzungskontext vorliegt.
        :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
        """
        ...

    def stoppen(self, name: str) -> str:
        """Beendet eine Sitzung.

        :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
        """
        ...

    def bildschirmfoto(self, rechner: str = "") -> tuple[str, str]:
        """Nimmt den Bildschirm eines Rechners auf.

        :returns: (Pfad, Fehlermeldung) - genau eines von beiden ist gefuellt.
        """
        ...

    def aktualisiere_claude(self, rechner: str = "", verfahren: str = "claude") -> tuple[str, str]:
        """Aktualisiert Claude Code auf einem Rechner.

        :param rechner: leer fuer diesen Rechner, sonst der Zielrechner.
        :param verfahren: wie installiert wurde - claude, npm, winget, choco, brew.
        :returns: (Version, Fehlermeldung) - genau eines von beiden ist gefuellt.
        """
        ...
