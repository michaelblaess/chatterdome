"""Auswahl und Kennzahlen der Bus-Ansicht.

Geprueft wird das Verhalten an Randfaellen, nicht die Existenz von Feldern:
fehlender Zeitstempel, Altbestand ohne Bindung, Suche ueber Quittungsnotizen.
Jede Pruefung wuerde rot, wenn der jeweilige Zweig fiele.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chatterdome.kern.busansicht import alter_stunden, filtere, kennzahlen
from chatterdome.kern.modelle import Auftrag, Ereignis

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def auftrag(
    kennung: str = "a1",
    *,
    zustand: str = "submitted",
    von: str = "Chatterdome",
    an: str = "Marga",
    text: str = "gib mir das aktuelle Datum",
    topic: str = "allgemein",
    vor_stunden: float = 1.0,
    an_session: str = "",
    bindung: str = "session",
    notiz: str = "",
) -> Auftrag:
    erstellt = (JETZT - timedelta(hours=vor_stunden)).isoformat().replace("+00:00", "Z")
    verlauf = []
    if notiz:
        verlauf.append(Ereignis(art="quittung", ts=erstellt, notiz=notiz, status=410))
    return Auftrag(
        auftrag_id=kennung,
        zustand=zustand,
        von=von,
        an=an,
        topic=topic,
        text=text,
        erstellt=erstellt,
        an_session=an_session,
        bindung=bindung,
        verlauf=verlauf,
    )


class TestZeitraum:
    def test_alt_faellt_aus_dem_fenster(self) -> None:
        bestand = [auftrag("frisch", vor_stunden=2), auftrag("alt", vor_stunden=96)]

        treffer = filtere(bestand, zeitraum="24h", jetzt=JETZT)

        assert [a.auftrag_id for a in treffer] == ["frisch"]

    def test_ohne_zeitraum_bleibt_alles(self) -> None:
        bestand = [auftrag("frisch", vor_stunden=2), auftrag("alt", vor_stunden=96)]

        assert len(filtere(bestand, zeitraum="alle", jetzt=JETZT)) == 2

    def test_unlesbarer_zeitstempel_bleibt_sichtbar(self) -> None:
        """Sonst verschwindet ausgerechnet der auffaellige Eintrag lautlos."""
        kaputt = auftrag("kaputt")
        kaputt.erstellt = "kein Datum"

        assert filtere([kaputt], zeitraum="24h", jetzt=JETZT) == [kaputt]


class TestZustand:
    @pytest.mark.parametrize(
        ("gruppe", "erwartet"),
        [
            ("alle", {"offen", "fertig", "weg", "verfallen"}),
            ("offen", {"offen"}),
            ("erledigt", {"fertig"}),
            ("gescheitert", {"weg", "verfallen"}),
        ],
    )
    def test_gruppen(self, gruppe: str, erwartet: set[str]) -> None:
        bestand = [
            auftrag("offen", zustand="submitted"),
            auftrag("fertig", zustand="completed"),
            auftrag("weg", zustand="cancelled"),
            auftrag("verfallen", zustand="expired"),
        ]

        assert {a.auftrag_id for a in filtere(bestand, gruppe=gruppe)} == erwartet


class TestBindung:
    def test_person_und_rolle_trennen(self) -> None:
        bestand = [
            auftrag("person", an_session="4d0c0ab0", bindung="session"),
            auftrag("rolle", an_session="", bindung="rolle"),
        ]

        assert [a.auftrag_id for a in filtere(bestand, bindung="person")] == ["person"]
        assert [a.auftrag_id for a in filtere(bestand, bindung="rolle")] == ["rolle"]


class TestSuche:
    def test_findet_ueber_agent_und_inhalt(self) -> None:
        bestand = [
            auftrag("a", an="Marga", text="gib mir das aktuelle Datum"),
            auftrag("b", an="Schmid", text="Kudu-Skript ablegen"),
        ]

        assert [x.auftrag_id for x in filtere(bestand, suche="marga")] == ["a"]
        assert [x.auftrag_id for x in filtere(bestand, suche="KUDU")] == ["b"]

    def test_findet_ueber_die_quittungsnotiz(self) -> None:
        """Dort steht der Grund - danach sucht man am ehesten."""
        bestand = [
            auftrag("a", notiz="Empfaenger Marga ist beendet"),
            auftrag("b", an="Schmid", text="etwas anderes"),
        ]

        assert [x.auftrag_id for x in filtere(bestand, suche="beendet")] == ["a"]

    def test_kriterien_wirken_zusammen(self) -> None:
        bestand = [
            auftrag("a", an="Marga", zustand="submitted"),
            auftrag("b", an="Marga", zustand="completed"),
        ]

        treffer = filtere(bestand, gruppe="offen", suche="marga")

        assert [x.auftrag_id for x in treffer] == ["a"]


class TestKennzahlen:
    def test_zaehlt_nach_zustand(self) -> None:
        bestand = [
            auftrag("1", zustand="submitted"),
            auftrag("2", zustand="working"),
            auftrag("3", zustand="completed"),
            auftrag("4", zustand="expired"),
        ]

        k = kennzahlen(bestand)

        assert (k.gesamt, k.offen, k.erledigt, k.gescheitert) == (4, 2, 1, 1)

    def test_findet_den_aeltesten_offenen(self) -> None:
        bestand = [
            auftrag("jung", vor_stunden=1),
            auftrag("alt", vor_stunden=96),
            # Erledigtes zaehlt nicht mit - es wartet auf niemanden mehr.
            auftrag("uralt_aber_fertig", vor_stunden=500, zustand="completed"),
        ]

        k = kennzahlen(bestand)

        assert k.aeltester_offen is not None
        assert k.aeltester_offen.auftrag_id == "alt"

    def test_zaehlt_die_vererbbaren_offenen(self) -> None:
        """Genau diese Zahl haette den Vorfall vom 07.08.2026 vorhergesagt."""
        bestand = [
            auftrag("gebunden", an_session="4d0c0ab0", bindung="session"),
            auftrag("rolle", an_session="", bindung="rolle"),
            auftrag("altbestand", an_session="", bindung=""),
            # Erledigtes kann niemand mehr erben.
            auftrag("fertig", an_session="", bindung="rolle", zustand="completed"),
        ]

        assert kennzahlen(bestand).ohne_bindung_offen == 2


class TestAlter:
    def test_rechnet_in_stunden(self) -> None:
        assert alter_stunden(auftrag(vor_stunden=48), jetzt=JETZT) == pytest.approx(48.0)

    def test_ohne_zeitstempel_kein_alter(self) -> None:
        ohne = auftrag()
        ohne.erstellt = ""

        assert alter_stunden(ohne, jetzt=JETZT) is None
