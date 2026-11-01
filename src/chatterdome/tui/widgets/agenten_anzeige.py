"""Wie die Werte eines Agenten aussehen - gilt fuer Tabelle und Kacheln.

Zwei Ansichten desselben Bestands muessen dieselben Zahlen und dieselben Farben
zeigen. Deshalb steht das hier und nicht in einer der beiden.
"""

from __future__ import annotations

from datetime import datetime

from chatterdome.i18n import t
from chatterdome.kern.modelle import Ampel

# Feste Ampelfarben statt Theme-Variablen oder benannter ANSI-Farben: eine
# Ampel hat rot, gelb und gruen, und die muessen auf jedem Theme genau so
# aussehen. Die benannte Farbe "yellow" ist in vielen Terminal-Paletten ein
# Orange - damit wird aus der Ampel eine vierte Farbe, die es nicht gibt.
AMPEL_FARBE = {
    Ampel.FREI: "bold #2ecc71",
    Ampel.BESCHAEFTIGT: "bold #f1c40f",
    Ampel.WEG: "bold #e74c3c",
}

BLINK_STIL = "bold #ffffff on #e74c3c"
"""Die helle Phase: weiss auf dem Warnrot der Ampel. Feste Farben statt Theme-Variablen,
weil die Farbe hier die Aussage ist."""


def _tokens(wert: int) -> str:
    if wert <= 0:
        return "-"
    return str(wert) if wert < 10_000 else f"{round(wert / 1000)}k"


def _dauer(ms: int) -> str:
    minuten = ms // 60_000
    if minuten < 60:
        return f"{minuten}m"
    return f"{minuten // 60}h {minuten % 60:02d}m"


def _alter(zeitpunkt: str, jetzt: datetime | None = None) -> str:
    """Abstand zum letzten Eintrag, kompakt: ``4 min``, ``2 h``, ``3 d``.

    In der Tabelle steht bewusst das Alter und nicht der Zeitstempel: die
    Frage lautet "wie lange ist da nichts mehr passiert", und die beantwortet
    ein Abstand ohne Kopfrechnen - bei einem Drittel der Spaltenbreite. Der
    genaue Zeitpunkt haengt als Hinweis an der Zelle und steht im Detail.
    """
    if not zeitpunkt:
        return "-"
    try:
        wert = datetime.fromisoformat(zeitpunkt.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return "?"
    bezug = jetzt.astimezone() if jetzt is not None else datetime.now().astimezone()
    minuten = int((bezug - wert).total_seconds() // 60)
    if minuten < 1:
        return t("age.now")
    if minuten < 60:
        return f"{minuten} min"
    if minuten < 60 * 24:
        return f"{minuten // 60} h"
    return f"{minuten // (60 * 24)} d"


AUFGABEN_BREITE = 30
"""Deckel fuer die Aufgabenspalte.

Gemessen an einem Fenster von 120 Zeichen: die Tabelle sieht davon rund 70,
und bei 40 Zeichen Aufgabe schiebt allein diese Spalte Kontext und Post aus
dem Bild. Bei 30 bleiben sie stehen, und kurze Auftraege brauchen ohnehin
weniger - die Spalte waechst nur so weit wie ihr laengster Text.
"""


def _aufgabe(text: str, breite: int = AUFGABEN_BREITE) -> str:
    """Kuerzt von rechts - der Anfang eines Auftrags traegt die Aussage.

    Ohne Deckel wuerde die Spalte so breit wie der laengste Auftragstext,
    und die Tabelle waere nur noch seitlich zu lesen. Der volle Text steht
    im Hinweis unter der Maus und in der Detailansicht.
    """
    einzeilig = " ".join(text.split())
    if len(einzeilig) <= breite:
        return einzeilig
    return einzeilig[: breite - 3].rstrip() + "..."
