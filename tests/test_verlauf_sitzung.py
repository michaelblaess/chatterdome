"""Der Verlauf haengt an der Sitzung, nicht am Namen.

Aufgefallen am 15.09.2026: unter "Charlene" standen Auftraege vom 31.07. an eine
laengst beendete Sitzung, und die Uhrzeit ohne Datum liess sie wie heutige
aussehen. Die Zuordnung selbst prueft ``skills/claude-bus/bus.test.mjs``, hier
geht es um das, was die Oberflaeche dazu beitraegt.
"""

from __future__ import annotations

import sys
from datetime import date, datetime

from claude_sanctuary.i18n import format_time, load_locale
from claude_sanctuary.kern.lokale_quelle import LokaleQuelle
from claude_sanctuary.kern.modelle import startzeit

# Gibt die eigenen Argumente als Auftragstext zurueck - so sieht der Test, was
# die Quelle dem Bus tatsaechlich uebergibt.
ECHO = (
    "import json, sys\n"
    "print(json.dumps({'auftraege': [{'auftrag_id': 'x', 'zustand': 'completed',"
    " 'text': ' '.join(sys.argv[1:])}]}))\n"
)


class TestStartzeit:
    def test_zieht_die_laufzeit_ab(self) -> None:
        assert startzeit("2026-09-15T18:00:00.000Z", 3_600_000) == "2026-09-15T17:00:00+00:00"

    def test_ohne_laufzeit_keine_behauptung(self) -> None:
        assert startzeit("2026-09-15T18:00:00.000Z", 0) == ""

    def test_ohne_zeitzone_keine_behauptung(self) -> None:
        assert startzeit("2026-09-15T18:00:00", 1000) == ""

    def test_kaputter_bezug_keine_behauptung(self) -> None:
        assert startzeit("gestern", 1000) == ""


class TestFormatTime:
    ZEITPUNKT = "2026-07-31T19:28:46.613Z"

    def _ortszeit(self) -> datetime:
        return datetime.fromisoformat(self.ZEITPUNKT.replace("Z", "+00:00")).astimezone()

    def test_heute_nur_die_uhrzeit(self) -> None:
        wert = self._ortszeit()
        assert format_time(self.ZEITPUNKT, heute=wert.date()) == wert.strftime("%H:%M")

    def test_anderer_tag_mit_datum(self) -> None:
        load_locale("de")
        wert = self._ortszeit()
        ergebnis = format_time(self.ZEITPUNKT, heute=date(2026, 9, 15))
        assert ergebnis == wert.strftime("%d.%m.%Y %H:%M")


class TestLokaleQuelleVerlauf:
    def test_reicht_sitzung_und_startzeit_durch(self) -> None:
        quelle = LokaleQuelle([sys.executable, "-c", ECHO])
        [auftrag] = quelle.verlauf(
            "Charlene", session_id="sid-neu", seit="2026-09-15T17:00:00+00:00"
        )
        assert auftrag.text == (
            "history Charlene --json --session sid-neu --since 2026-09-15T17:00:00+00:00"
        )

    def test_ohne_sitzung_nur_der_name(self) -> None:
        quelle = LokaleQuelle([sys.executable, "-c", ECHO])
        [auftrag] = quelle.verlauf("Charlene")
        assert auftrag.text == "history Charlene --json"

    def test_startzeit_ohne_sitzung_wird_nicht_gesendet(self) -> None:
        quelle = LokaleQuelle([sys.executable, "-c", ECHO])
        [auftrag] = quelle.verlauf("Charlene", seit="2026-09-15T17:00:00+00:00")
        assert auftrag.text == "history Charlene --json"
