"""Was die Oberflaeche zeigt, solange ein Auftrag noch offen ist.

Michaels Wunsch vom 21.08.2026: waehrend man auf die Antwort einer anderen
Instanz wartet, soll sichtbar sein, dass etwas passiert - laufende Punkte, die
von der echten Antwort abgeloest werden.

DIE PUNKTE HAENGEN AM ZUSTAND, NICHT AN EINER UHR. Eine Animation, die einfach
laeuft, behauptet Fortschritt: sie liefe genauso munter, wenn die Empfaengerin
den Auftrag nie bekommen hat, im Freigabedialog haengt oder schlicht nichts
tut. Genau diese Sorte Anzeige steht als offener Fehler bei Anthropic
(Issue #88231: ``delivered:true`` fuer tote Ziele). Der Bus kennt den
tatsaechlichen Zustand - also zeigt die Oberflaeche den, und die Punkte sind
nur das Zeichen dafuer, dass weiter gewartet wird.

Und sie hoeren auf. Punkte, die ewig laufen, sind schlimmer als gar keine:
nach der Frist steht dort, wie lange nichts passiert ist, statt einer
Bewegung, die Zuversicht vortaeuscht.
"""

from __future__ import annotations

from dataclasses import dataclass

# Zustaende, in denen noch etwas kommen kann. Deckungsgleich mit OFFEN in
# speicher.mjs - waeren sie es nicht, zeigte die Oberflaeche Punkte fuer
# Auftraege, die der Bus laengst abgehakt hat.
OFFENE_ZUSTAENDE = ("submitted", "working", "input_required")

PUNKTE_TAKTE = 4
"""Wie viele Bilder die Animation hat: keiner, einer, zwei, drei Punkte."""

VERSTUMMT_NACH_S = 120.0
"""Ab hier wird nicht mehr animiert, sondern die Stille benannt."""


@dataclass(frozen=True, slots=True)
class Warteanzeige:
    """Was an die Zustandszeile angehaengt wird."""

    punkte: str
    """Null bis drei Punkte, leer wenn nicht mehr animiert wird."""

    sekunden: int
    """Wie lange dieser Zustand schon anhaelt, abgerundet."""

    verstummt: bool
    """True, wenn die Frist abgelaufen ist - dann erwartet niemand mehr etwas."""


def warteanzeige(
    zustand: str,
    sekunden: float,
    takt: int,
    frist: float = VERSTUMMT_NACH_S,
) -> Warteanzeige | None:
    """Entscheidet, ob und wie gewartet angezeigt wird.

    :param zustand: Zustand des Auftrags, wie ihn der Bus fuehrt.
    :param sekunden: Wie lange der Zustand schon anhaelt.
    :param takt: Fortlaufender Zaehler der Oberflaeche, bestimmt das Bild.
    :param frist: Ab wann nicht mehr animiert wird.
    :returns: ``None``, wenn nichts anzuzeigen ist - also bei jedem
        abgeschlossenen Auftrag. Sonst die Anzeige.
    """
    if zustand not in OFFENE_ZUSTAENDE:
        return None
    # Eine negative Dauer gibt es nicht: bei ungleichen Uhren im Mesh kann der
    # Zeitstempel in der Zukunft liegen, und "-3 s" waere Unsinn.
    vergangen = max(0.0, sekunden)
    if vergangen >= frist:
        return Warteanzeige(punkte="", sekunden=int(vergangen), verstummt=True)
    return Warteanzeige(
        punkte="." * (takt % PUNKTE_TAKTE),
        sekunden=int(vergangen),
        verstummt=False,
    )


def dauer_kurz(sekunden: int) -> str:
    """Verstrichene Zeit als ``0:07`` oder ``2:14``.

    Bewusst Minuten und Sekunden statt "vor 7 Sekunden": die Zahl steht
    unmittelbar neben einer Animation und wird im Sekundentakt neu gelesen -
    da zaehlt Kuerze mehr als Sprachfluss.
    """
    sicher = max(0, sekunden)
    return f"{sicher // 60}:{sicher % 60:02d}"
