"""Auswahl und Kennzahlen fuer die Bus-Ansicht - ohne jede Oberflaeche.

Bewusst hier und nicht im Widget: Filtern ist Logik mit Randfaellen (fehlende
Zeitstempel, Grossschreibung, Altbestand ohne Bindung), und Logik in einem
Widget laesst sich nur ueber die Oberflaeche pruefen. Hier laeuft ein Test in
Millisekunden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from claude_sanctuary.kern.modelle import (
    GESCHEITERTE_ZUSTAENDE,
    OFFENE_ZUSTAENDE,
    Auftrag,
)

ZEITRAEUME: dict[str, int] = {
    "alle": 0,
    "24h": 24,
    "7d": 24 * 7,
    "30d": 24 * 30,
}
"""Auswahlwert auf Stunden. 0 heisst ohne Begrenzung."""

ZUSTANDSGRUPPEN: dict[str, frozenset[str]] = {
    "alle": frozenset(),
    "offen": OFFENE_ZUSTAENDE,
    "erledigt": frozenset({"completed"}),
    "gescheitert": GESCHEITERTE_ZUSTAENDE,
}
"""Auswahlwert auf Zustaende. Eine leere Menge heisst "nicht einschraenken".

Gruppen statt einzelner Zustaende: die Frage lautet "liegt noch etwas an",
nicht "steht dieser Auftrag auf input_required".
"""

BINDUNGSARTEN = ("alle", "person", "rolle")


def _zeitpunkt(iso: str) -> datetime | None:
    """Liest einen Zeitstempel des Bus. None, wenn er fehlt oder unlesbar ist.

    Ein unlesbarer Zeitstempel darf NICHT als "sehr alt" durchgehen: sonst
    verschwindet der Auftrag beim kleinsten Zeitfilter aus der Ansicht, und
    genau der waere der interessante.
    """
    if not iso:
        return None
    try:
        gelesen = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return gelesen if gelesen.tzinfo else gelesen.replace(tzinfo=UTC)


def _ist_person(auftrag: Auftrag) -> bool:
    return bool(auftrag.an_session)


def filtere(
    auftraege: list[Auftrag],
    *,
    zeitraum: str = "alle",
    gruppe: str = "alle",
    bindung: str = "alle",
    suche: str = "",
    jetzt: datetime | None = None,
) -> list[Auftrag]:
    """Waehlt aus dem Bestand aus. Alle Kriterien wirken zusammen (und).

    :param suche:
        Freitext ueber Absender, Empfaenger, Thema, Inhalt und Auftrags-ID.
        Gross- und Kleinschreibung spielen keine Rolle.
    :param jetzt:
        Bezugszeit fuer den Zeitraum. Nur fuer Tests von aussen zu setzen.
    """
    stunden = ZEITRAEUME.get(zeitraum, 0)
    zustaende = ZUSTANDSGRUPPEN.get(gruppe, frozenset())
    nadel = " ".join(suche.split()).casefold()
    grenze = (jetzt or datetime.now(UTC)) - timedelta(hours=stunden) if stunden else None

    treffer = []
    for a in auftraege:
        if zustaende and a.zustand not in zustaende:
            continue
        if grenze is not None:
            wann = _zeitpunkt(a.erstellt)
            if wann is not None and wann < grenze:
                continue
        if bindung == "person" and not _ist_person(a):
            continue
        if bindung == "rolle" and _ist_person(a):
            continue
        if nadel and nadel not in _heuhaufen(a):
            continue
        treffer.append(a)
    return treffer


def _heuhaufen(a: Auftrag) -> str:
    """Alles, worin die Suche fuendig werden darf, in einer Zeichenkette.

    Die Quittungsnotizen gehoeren dazu: dort steht der Grund, warum ein Auftrag
    verfallen oder zurueckgenommen wurde, und danach sucht man am ehesten.
    """
    teile = [a.von, a.an, a.topic, a.text, a.auftrag_id, a.zustand]
    teile += [e.notiz for e in a.verlauf if e.notiz]
    return " ".join(teile).casefold()


@dataclass(slots=True)
class Kennzahlen:
    """Was im Bus liegt, auf einen Blick."""

    gesamt: int = 0
    offen: int = 0
    erledigt: int = 0
    gescheitert: int = 0
    je_zustand: dict[str, int] = field(default_factory=dict)
    aeltester_offen: Auftrag | None = None
    ohne_bindung_offen: int = 0
    """Offene Auftraege, die an einen NAMEN gehen statt an eine Sitzung.

    Das ist die Zahl, die den Vorfall vom 07.08.2026 vorhersagt: nur solche
    Auftraege kann ein spaeterer Traeger desselben Namens erben.
    """


def kennzahlen(auftraege: list[Auftrag]) -> Kennzahlen:
    """Zaehlt den Bestand aus."""
    k = Kennzahlen(gesamt=len(auftraege))
    aeltester: datetime | None = None
    for a in auftraege:
        k.je_zustand[a.zustand] = k.je_zustand.get(a.zustand, 0) + 1
        if a.zustand in OFFENE_ZUSTAENDE:
            k.offen += 1
            if not _ist_person(a):
                k.ohne_bindung_offen += 1
            wann = _zeitpunkt(a.erstellt)
            if wann is not None and (aeltester is None or wann < aeltester):
                aeltester = wann
                k.aeltester_offen = a
        elif a.zustand == "completed":
            k.erledigt += 1
        elif a.zustand in GESCHEITERTE_ZUSTAENDE:
            k.gescheitert += 1
    return k


def alter_stunden(auftrag: Auftrag, jetzt: datetime | None = None) -> float | None:
    """Alter eines Auftrags in Stunden, oder None ohne lesbaren Zeitstempel."""
    wann = _zeitpunkt(auftrag.erstellt)
    if wann is None:
        return None
    return ((jetzt or datetime.now(UTC)) - wann).total_seconds() / 3600.0
