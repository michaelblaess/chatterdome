"""Der Chatbot der Kachelansicht, gezeichnet aus Halbbloecken.

Bewusst Text und keine Grafik: TGP und Sixel liegen ausserhalb des Textrasters,
jeder Dialog wischt sie weg, und fest eingebaut koennen sie Windows Terminal den
ganzen Bildschirm leeren. Halbbloecke laufen ueberall - und sie lassen sich im
Takt neu zeichnen, was die Augen ueberhaupt erst beweglich macht.

Ein Zeichen haelt zwei Pixel uebereinander, die Vordergrundfarbe das obere und
die Hintergrundfarbe das untere. Aus zehn Pixelzeilen werden so fuenf Textzeilen.
"""

from __future__ import annotations

import zlib
from enum import Enum

from rich.text import Text

BREITE = 16
"""Pixel je Zeile, zugleich Zeichen je Textzeile."""

HOEHE = 10
"""Pixelzeilen. Immer gerade, je zwei ergeben eine Textzeile."""

# K ist das Gehaeuse, S der Bildschirm, A das Licht an der Antenne. Alle Koepfe
# haben den Bildschirm an derselben Stelle, das Gesicht passt deshalb auf jeden.
_KOEPFE: tuple[tuple[str, ...], ...] = (
    (
        ".......AA.......",
        ".......KK.......",
        "...KKKKKKKKKK...",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "...KKKKKKKKKK...",
        ".....KK..KK.....",
    ),
    (
        "...A........A...",
        "...K........K...",
        "..KKKKKKKKKKKK..",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "..KKKKKKKKKKKK..",
        "....KKK..KKK....",
    ),
    (
        ".......AA.......",
        "......KKKK......",
        "..KKKKKKKKKKKK..",
        "..KSSSSSSSSSSK..",
        "KKKSSSSSSSSSSKKK",
        "KKKSSSSSSSSSSKKK",
        "..KSSSSSSSSSSK..",
        "..KSSSSSSSSSSK..",
        "...KKKKKKKKKK...",
        "......KKKK......",
    ),
)

# Bewusst ohne Gruen, Gelb und Rot in Reinform: die gehoeren der Ampel.
_GEHAEUSE = (
    "#3f9bd9",
    "#2aa198",
    "#e08a3c",
    "#d9668f",
    "#8fb339",
    "#c9a227",
    "#39b7cd",
    "#d97a5f",
    "#8ca0b3",
)

_BILDSCHIRM = "#10161c"
_AUGE_WACH = "#d8f6ff"
_AUGE_ARBEIT = "#f1c40f"
_AUGE_SCHLAF = "#6b7c8c"
_AUGE_AUS = "#e74c3c"


class Gesicht(Enum):
    """Was der Roboter gerade macht."""

    WACH = "wach"
    BLINZELT = "blinzelt"
    ARBEITET = "arbeitet"
    SCHLAEFT = "schlaeft"
    AUS = "aus"


def kennzahl(name: str) -> int:
    """Eine Zahl, die fuer denselben Namen immer gleich ist.

    Nicht ``hash()``: der wird je Prozess neu gewuerfelt, und Agatha saehe nach
    jedem Start anders aus.
    """
    return zlib.crc32(name.casefold().encode("utf-8"))


def gehaeusefarbe(name: str) -> str:
    """Die Farbe, die dieser Name immer bekommt."""
    return _GEHAEUSE[kennzahl(name) % len(_GEHAEUSE)]


def kopf_nummer(name: str) -> int:
    """Die Kopfform, die dieser Name immer bekommt."""
    # Andere Bits als bei der Farbe, sonst haengt die Form an der Farbe.
    return (kennzahl(name) >> 8) % len(_KOEPFE)


def abdunkeln(farbe: str, faktor: float) -> str:
    """Zieht eine ``#rrggbb``-Farbe Richtung Schwarz."""
    wert = int(farbe.removeprefix("#"), 16)
    teile = ((wert >> 16) & 255, (wert >> 8) & 255, wert & 255)
    return "#" + "".join(f"{round(teil * faktor):02x}" for teil in teile)


def _gesichtspunkte(gesicht: Gesicht, blick: int) -> list[tuple[int, int]]:
    """Die Pixel des Gesichts als (x, y).

    :param gesicht: Der Zustand.
    :param blick: Versatz der Augen nach links oder rechts, -1 bis 1.
    """
    if gesicht is Gesicht.AUS:
        kreuz = ((0, 0), (2, 0), (1, 1), (0, 2), (2, 2))
        augen = [(x + links, y + 3) for links in (4, 9) for x, y in kreuz]
        return [*augen, *((x, 7) for x in range(6, 10))]
    if gesicht is Gesicht.SCHLAEFT:
        augen = [(x, 4) for x in (5, 6, 9, 10)]
        return [*augen, (7, 7), (8, 7)]

    zeilen = (4,) if gesicht is Gesicht.BLINZELT else (3, 4)
    augen = [(x + blick, y) for x in (5, 6, 9, 10) for y in zeilen]
    if gesicht is Gesicht.ARBEITET:
        return [*augen, *((x, 7) for x in range(6, 10))]
    return [*augen, (5, 6), (10, 6), *((x, 7) for x in range(6, 10))]


def _augenfarbe(gesicht: Gesicht) -> str:
    if gesicht is Gesicht.ARBEITET:
        return _AUGE_ARBEIT
    if gesicht is Gesicht.SCHLAEFT:
        return _AUGE_SCHLAF
    return _AUGE_AUS if gesicht is Gesicht.AUS else _AUGE_WACH


def zeichne(
    name: str,
    gesicht: Gesicht,
    licht: str,
    blick: int = 0,
    gedimmt: bool = False,
) -> list[Text]:
    """Zeichnet den Roboter dieses Namens.

    :param name: Bestimmt Farbe und Kopfform.
    :param gesicht: Was er gerade macht.
    :param licht: Farbe des Antennenlichts.
    :param blick: Versatz der Augen, -1 bis 1.
    :param gedimmt: Ob das Gehaeuse abgedunkelt wird, fuer verwaiste und tote Sitzungen.
    :returns: Eine Textzeile je zwei Pixelzeilen, jede ``BREITE`` Zeichen lang.
    """
    raster = [list(zeile) for zeile in _KOEPFE[kopf_nummer(name)]]
    for x, y in _gesichtspunkte(gesicht, blick):
        raster[y][x] = "E"

    gehaeuse = gehaeusefarbe(name)
    farben = {
        "K": abdunkeln(gehaeuse, 0.45) if gedimmt else gehaeuse,
        "S": _BILDSCHIRM,
        "A": licht,
        "E": _augenfarbe(gesicht),
    }
    zeilen: list[Text] = []
    for y in range(0, HOEHE, 2):
        zeile = Text(no_wrap=True)
        for oben_zeichen, unten_zeichen in zip(raster[y], raster[y + 1], strict=True):
            oben = farben.get(oben_zeichen)
            unten = farben.get(unten_zeichen)
            if oben is None and unten is None:
                zeile.append(" ")
            elif unten is None:
                zeile.append("▀", style=oben or "")
            elif oben is None:
                zeile.append("▄", style=unten)
            elif oben == unten:
                zeile.append("█", style=oben)
            else:
                zeile.append("▀", style=f"{oben} on {unten}")
        zeilen.append(zeile)
    return zeilen
