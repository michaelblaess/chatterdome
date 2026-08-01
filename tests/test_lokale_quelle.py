"""Tests der Anbindung an den Kurzbefehl.

Statt des echten ``sanctuary`` laeuft ein Python-Einzeiler, der eine feste
Antwort ausgibt. Damit ist der Umgang mit der Ausgabe geprueft, ohne dass ein
laufender Bus noetig waere.
"""

from __future__ import annotations

import json
import sys

from claude_sanctuary.kern.lokale_quelle import LokaleQuelle
from claude_sanctuary.kern.modelle import Ampel

ANTWORT = {
    "rechner": "TESTHOST",
    "zeit": "2026-08-01T19:00:00.000Z",
    "anzahl": 2,
    "instanzen": [
        {
            "name": "Klara",
            "status": "idle",
            "pid": 111,
            "sessionId": "abc",
            "selbst": False,
            "laufzeit": 3_600_000,
            "post": 2,
            "kontext": 700_000,
            "tokens": 12_345,
            "cacheGelesen": 999,
            "modell": "claude-opus-5",
            "letztesTool": "Bash",
            "cwd": "C:\\Repos\\test",
        },
        {
            "name": "Lino",
            "status": "busy",
            "pid": 222,
            "sessionId": "def",
            "selbst": True,
            "laufzeit": 60_000,
            "post": 0,
            "kontext": 1000,
            "tokens": 0,
            "modell": None,
            "cwd": "~",
        },
    ],
}

MESH = {
    "zeit": "2026-08-01T20:39:10.779Z",
    "rechner": [
        {
            "host": "rainbow",
            "rechner": "RAINBOW",
            "instanzen": [
                {"name": "Operator", "status": "busy", "selbst": True, "post": 1},
                {"name": "Marga", "status": "idle"},
            ],
        },
        {
            "host": "senza",
            "rechner": "SENZA",
            "instanzen": [{"name": "Lino", "status": "idle", "tokens": 42}],
        },
        {"host": "dell", "rechner": "DELL", "instanzen": [], "fehler": "offline (Tailscale)"},
    ],
}

VERLAUF = {
    "rechner": "TESTHOST",
    "ich": "Operator",
    "partner": "Klara",
    "auftraege": [
        {
            "auftrag_id": "a1",
            "zustand": "completed",
            "von": "Operator",
            "an": "Klara",
            "topic": "test",
            "text": "Bitte pruefen",
            "erstellt": "2026-08-01T10:00:00.000Z",
            "quittungen": [
                {
                    "ts": "2026-08-01T10:05:00.000Z",
                    "von": "Klara",
                    "an": "Operator",
                    "zustand": "completed",
                    "status": 200,
                    "notiz": "erledigt",
                }
            ],
        }
    ],
}


def _quelle(nutzlast: dict[str, object]) -> LokaleQuelle:
    """Baut eine Quelle, deren Befehl eine feste Antwort ausgibt."""
    skript = f"import sys; sys.stdout.write({json.dumps(json.dumps(nutzlast))})"
    return LokaleQuelle([sys.executable, "-c", skript])


class TestBestand:
    def test_liest_agenten(self) -> None:
        bestand = _quelle(ANTWORT).bestand()
        assert bestand.rechner == "TESTHOST"
        assert [a.name for a in bestand.agenten] == ["Klara", "Lino"]

    def test_uebernimmt_felder(self) -> None:
        klara = _quelle(ANTWORT).bestand().agenten[0]
        assert klara.post == 2
        assert klara.kontext == 700_000
        assert klara.kontext_eng
        assert not klara.kontext_kritisch
        assert klara.ampel is Ampel.FREI
        assert klara.cache_gelesen == 999

    def test_fehlende_felder_werden_nicht_geraten(self) -> None:
        lino = _quelle(ANTWORT).bestand().agenten[1]
        assert lino.modell is None
        assert lino.letztes_tool is None
        assert lino.ampel is Ampel.BESCHAEFTIGT

    def test_summen(self) -> None:
        bestand = _quelle(ANTWORT).bestand()
        assert bestand.offene_auftraege == 2
        assert bestand.beschaeftigt == 1

    def test_unbekannter_befehl_meldet_fehler(self) -> None:
        quelle = LokaleQuelle(["gibt-es-ganz-sicher-nicht-12345"])
        bestand = quelle.bestand()
        assert bestand.agenten == []
        assert bestand.fehler
        assert "nicht gefunden" in bestand.fehler[0]

    def test_kaputte_antwort_meldet_fehler(self) -> None:
        quelle = LokaleQuelle([sys.executable, "-c", "print('kein json')"])
        bestand = quelle.bestand()
        assert bestand.agenten == []
        assert "JSON" in bestand.fehler[0]


class TestVerlauf:
    def test_auftrag_und_quittung_werden_blasen(self) -> None:
        auftraege = _quelle(VERLAUF).verlauf("Klara")
        assert len(auftraege) == 1
        verlauf = auftraege[0].verlauf
        assert len(verlauf) == 2
        assert verlauf[0].eigen is True
        assert verlauf[0].text == "Bitte pruefen"
        assert verlauf[1].eigen is False
        assert verlauf[1].status == 200

    def test_fehler_liefert_leere_liste(self) -> None:
        quelle = LokaleQuelle(["gibt-es-ganz-sicher-nicht-12345"])
        assert quelle.verlauf("Klara") == []


class TestMesh:
    """Die Mesh-Ausgabe hat eine ANDERE Struktur als die lokale.

    Lokal steht unter "rechner" ein Name und daneben "instanzen". Bei --mesh
    ist "rechner" eine Liste von Zweigen, und "instanzen" gibt es oben gar
    nicht. Wer nur den lokalen Fall liest, bekommt still eine leere Liste.
    """

    def test_agenten_aller_hosts(self) -> None:
        bestand = _quelle(MESH).bestand(mesh=True)
        assert [a.name for a in bestand.agenten] == ["Operator", "Marga", "Lino"]

    def test_rechner_wird_je_zweig_uebernommen(self) -> None:
        agenten = {a.name: a.rechner for a in _quelle(MESH).bestand(mesh=True).agenten}
        assert agenten["Operator"] == "RAINBOW"
        assert agenten["Lino"] == "SENZA"

    def test_nicht_erreichbarer_host_wird_gemeldet(self) -> None:
        bestand = _quelle(MESH).bestand(mesh=True)
        assert bestand.fehler == ["dell: offline (Tailscale)"]

    def test_summen_ueber_alle_hosts(self) -> None:
        bestand = _quelle(MESH).bestand(mesh=True)
        assert bestand.beschaeftigt == 1
        assert bestand.offene_auftraege == 1
        assert bestand.tokens == 42
