"""Auswertung der Transkripte und des Bus.

Geprueft wird an Randfaellen, nicht an Glueckspfaden: sich beruehrende
Intervalle, Tage ohne Verbrauch, ein Ausreisser im Median, eine leere
Instanzliste. Jede dieser Pruefungen wuerde rot, wenn der jeweilige Zweig
fiele - eine reine Summenpruefung waere in allen vier Faellen gruen geblieben.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chatterdome.kern.modelle import Auftrag, Ereignis
from chatterdome.kern.statistik import (
    Anfrage,
    Sitzungsspanne,
    alterskoerbe,
    bustage,
    durchlaufzeiten,
    fruehwarnung,
    hoechste_gleichzeitigkeit,
    lade_statistik,
    liegekoerbe,
    lies_anfragen,
    lies_namen,
    ordnerwerte,
    spannen,
    tagesreihe,
)

JETZT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _iso(stunden_vorher: float) -> str:
    return (JETZT - timedelta(hours=stunden_vorher)).isoformat().replace("+00:00", "Z")


def _anfrage(
    stunden_vorher: float = 1.0,
    *,
    sitzung: str = "s1",
    ordner: str = "repo",
    frisch: int = 100,
    cache_gelesen: int = 900,
    aus: int = 50,
) -> Anfrage:
    return Anfrage(
        ts=JETZT - timedelta(hours=stunden_vorher),
        sitzung=sitzung,
        ordner=ordner,
        frisch=frisch,
        cache_gelesen=cache_gelesen,
        aus=aus,
    )


# ---------------------------------------------------------------------------


class TestLesen:
    def _transkript(self, ordner: Path, name: str, zeilen: list[dict[str, object]]) -> None:
        ziel = ordner / "projekt"
        ziel.mkdir(exist_ok=True)
        (ziel / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(z) for z in zeilen) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def test_liest_verbrauch_und_ordner(self, tmp_path: Path) -> None:
        self._transkript(
            tmp_path,
            "a",
            [
                {"type": "agent-name", "agentName": "Marga · HE", "sessionId": "s1"},
                {
                    "type": "assistant",
                    "timestamp": _iso(1),
                    "sessionId": "s1",
                    "cwd": "C:/Repos/chatterdome",
                    "message": {
                        "usage": {
                            "input_tokens": 10,
                            "cache_creation_input_tokens": 20,
                            "cache_read_input_tokens": 30,
                            "output_tokens": 40,
                        }
                    },
                },
            ],
        )

        gelesen = list(lies_anfragen(tmp_path))

        assert len(gelesen) == 1
        assert gelesen[0].ordner == "chatterdome"
        assert gelesen[0].gesamt == 100
        # "echt" laesst die Cache-Lesung weg - das ist der ganze Zweck.
        assert gelesen[0].echt == 70

    def test_ueberspringt_kaputte_zeilen(self, tmp_path: Path) -> None:
        """Transkripte werden waehrend des Lesens weitergeschrieben."""
        ziel = tmp_path / "projekt"
        ziel.mkdir()
        gut = json.dumps(
            {
                "type": "assistant",
                "timestamp": _iso(1),
                "sessionId": "s1",
                "message": {"usage": {"output_tokens": 5}},
            }
        )
        (ziel / "a.jsonl").write_text(f"{gut}\n{{kaputt\n", encoding="utf-8", newline="\n")

        assert len(list(lies_anfragen(tmp_path))) == 1

    def test_fehlendes_verzeichnis_ist_kein_fehler(self, tmp_path: Path) -> None:
        assert list(lies_anfragen(tmp_path / "gibtsnicht")) == []

    def test_namen_ohne_ordnerzusatz(self, tmp_path: Path) -> None:
        self._transkript(
            tmp_path,
            "a",
            [{"type": "agent-name", "agentName": "Marga · BUERO_PC2", "sessionId": "s9"}],
        )

        assert lies_namen(tmp_path) == {"s9": "Marga"}


class TestGleichzeitigkeit:
    def test_zaehlt_ueberlappung(self) -> None:
        tag = JETZT.date()
        s = [
            Sitzungsspanne("a", beginn=JETZT - timedelta(hours=3), ende=JETZT - timedelta(hours=1)),
            Sitzungsspanne("b", beginn=JETZT - timedelta(hours=2), ende=JETZT),
        ]

        assert hoechste_gleichzeitigkeit(s, tag) == 2

    def test_beruehrung_ist_keine_ueberlappung(self) -> None:
        """Endet eine Sitzung genau, wenn die naechste beginnt, liefen nie zwei.

        Ohne die Sortierung "erst schliessen, dann oeffnen" meldet der Sweep
        hier eine Zwei - und die Flottenkurve waere durchgehend zu hoch.
        """
        tag = JETZT.date()
        grenze = JETZT - timedelta(hours=2)
        s = [
            Sitzungsspanne("a", beginn=JETZT - timedelta(hours=4), ende=grenze),
            Sitzungsspanne("b", beginn=grenze, ende=JETZT),
        ]

        assert hoechste_gleichzeitigkeit(s, tag) == 1

    def test_anderer_tag_zaehlt_nicht(self) -> None:
        s = [Sitzungsspanne("a", beginn=JETZT, ende=JETZT)]

        assert hoechste_gleichzeitigkeit(s, JETZT.date() - timedelta(days=3)) == 0


class TestTagesreihe:
    def test_luecken_bleiben_als_null(self) -> None:
        """Ein Diagramm, das arbeitsfreie Tage weglaesst, staucht die Achse."""
        von = JETZT.date() - timedelta(days=3)
        reihe = tagesreihe([_anfrage(1)], [], von=von, bis=JETZT.date())

        assert len(reihe) == 4
        assert [w.anfragen for w in reihe] == [0, 0, 0, 1]

    def test_trennt_die_verbrauchsarten(self) -> None:
        reihe = tagesreihe([_anfrage(1)], [], von=JETZT.date(), bis=JETZT.date())

        assert reihe[0].cache_gelesen == 900
        assert reihe[0].echt == 150
        # 900 von 1.050, nicht von 1.000 - der Anteil bezieht sich auf den
        # GESAMTverbrauch einschliesslich Ausgabe.
        assert reihe[0].cache_anteil == pytest.approx(900 / 1050, abs=0.001)

    def test_zaehlt_sitzungen_je_tag_ohne_doppelung(self) -> None:
        anfragen = [_anfrage(1, sitzung="s1"), _anfrage(2, sitzung="s1"), _anfrage(1, sitzung="s2")]

        reihe = tagesreihe(anfragen, [], von=JETZT.date(), bis=JETZT.date())

        assert reihe[0].sitzungen == 2


class TestSpannen:
    def test_fasst_je_sitzung_zusammen(self) -> None:
        anfragen = [_anfrage(5, sitzung="s1"), _anfrage(1, sitzung="s1")]

        [s] = spannen(anfragen, {"s1": "Marga"})

        assert s.name == "Marga"
        assert s.anfragen == 2
        assert s.stunden == pytest.approx(4.0)


class TestKoerbe:
    def test_alterskoerbe_nehmen_den_median(self) -> None:
        """Ein Ausreisser darf den Korb nicht allein bestimmen.

        Drei Sitzungen mit 1, 2 und 300 Millionen Token: der Mittelwert waere
        101, der Median 2. Genau deshalb steht dort der Median.
        """
        gemeinsam = {"beginn": JETZT - timedelta(hours=1), "ende": JETZT}
        s = [
            Sitzungsspanne("a", tokens=1_000_000, **gemeinsam),  # type: ignore[arg-type]
            Sitzungsspanne("b", tokens=2_000_000, **gemeinsam),  # type: ignore[arg-type]
            Sitzungsspanne("c", tokens=300_000_000, **gemeinsam),  # type: ignore[arg-type]
        ]

        koerbe = alterskoerbe(s)

        assert koerbe[0].label == "0-2 h"
        assert koerbe[0].anzahl == 3
        assert koerbe[0].tokens_median == 2_000_000

    def test_ordner_nach_verbrauch_sortiert(self) -> None:
        anfragen = [
            _anfrage(1, ordner="klein", frisch=1, cache_gelesen=1, aus=1),
            _anfrage(1, ordner="gross"),
            _anfrage(2, ordner="gross"),
        ]

        werte = ordnerwerte(anfragen)

        assert [o.ordner for o in werte] == ["gross", "klein"]
        assert werte[0].anfragen == 2

    def test_sortiert_nach_verarbeitetem_nicht_nach_gesamtsumme(self) -> None:
        """Die Anzeige zeigt das Verarbeitete - die Reihenfolge muss dazu passen.

        Sonst stehen die Balken nicht absteigend, und die Auswahl der ersten
        sechs trifft die falschen Ordner. Gemessen am 24.08.2026 stand der
        groesste Ordner dadurch auf Platz 6.
        """
        anfragen = [
            # Viel gelesener Kontext, wenig echte Arbeit.
            _anfrage(1, ordner="cache-lastig", frisch=1, cache_gelesen=9_000_000, aus=1),
            # Wenig Kontext, viel Arbeit.
            _anfrage(1, ordner="arbeitsam", frisch=500, cache_gelesen=10, aus=500),
        ]

        werte = ordnerwerte(anfragen)

        assert [o.ordner for o in werte] == ["arbeitsam", "cache-lastig"]


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


def _auftrag(
    kennung: str = "a1",
    *,
    zustand: str = "submitted",
    vor_stunden: float = 2.0,
    fertig_nach: float | None = None,
    an_session: str = "",
    angenommen_nach: float | None = None,
) -> Auftrag:
    erstellt = _iso(vor_stunden)
    verlauf = [Ereignis(art="auftrag", ts=erstellt)]
    if angenommen_nach is not None:
        verlauf.append(
            Ereignis(art="quittung", ts=_iso(vor_stunden - angenommen_nach), status=202)
        )
    geaendert = _iso(vor_stunden - fertig_nach) if fertig_nach is not None else erstellt
    return Auftrag(
        auftrag_id=kennung,
        zustand=zustand,
        von="Chatterdome",
        an="Marga",
        erstellt=erstellt,
        geaendert=geaendert,
        an_session=an_session,
        verlauf=verlauf,
    )


class TestBus:
    def test_tage_nach_ausgang_getrennt(self) -> None:
        liste = [
            _auftrag("1", zustand="completed"),
            _auftrag("2", zustand="expired"),
            _auftrag("3", zustand="cancelled"),
            _auftrag("4", zustand="submitted"),
        ]

        [tag] = bustage(liste, von=JETZT.date(), bis=JETZT.date())

        assert (tag.erledigt, tag.gescheitert, tag.offen) == (1, 2, 1)

    def test_liegezeit_nur_fuer_offene(self) -> None:
        liste = [
            _auftrag("offen", vor_stunden=3),
            _auftrag("fertig", zustand="completed", vor_stunden=100),
        ]

        koerbe = liegekoerbe(liste, JETZT)

        assert [(k.label, k.anzahl) for k in koerbe if k.anzahl] == [("1-6 h", 1)]

    def test_annahme_und_erledigung_getrennt(self) -> None:
        """Zwei verschiedene Aussagen - Erreichbarkeit gegen Arbeit."""
        liste = [
            _auftrag(
                "1", zustand="completed", vor_stunden=10, fertig_nach=8, angenommen_nach=1
            )
        ]

        fertig, annahme = durchlaufzeiten(liste)

        assert fertig == pytest.approx(8.0)
        assert annahme == pytest.approx(1.0)

    def test_ohne_quittung_keine_annahmezeit(self) -> None:
        _, annahme = durchlaufzeiten([_auftrag("1", zustand="completed", fertig_nach=1)])

        assert annahme is None


class TestFruehwarnung:
    def test_zaehlt_vererbbare_offene(self) -> None:
        liste = [
            _auftrag("rolle", an_session=""),
            _auftrag("person", an_session="s1"),
            _auftrag("fertig", zustand="completed", an_session=""),
        ]

        w = fruehwarnung(liste, [], {"s1"})

        assert w.vererbbar_offen == 1

    def test_leere_instanzliste_meldet_keine_waisen(self) -> None:
        """Fail-closed: eine leere Liste kann auch aus einem Fehler stammen.

        Wer daraus jeden Auftrag als verwaist meldet, erzeugt einen Fehlalarm
        auf ganzer Breite - dieselbe Regel wie beim Aufraeumen der Namen.
        """
        liste = [_auftrag("person", an_session="langst-weg")]

        assert fruehwarnung(liste, [], set()).verwaiste_auftraege == 0
        assert fruehwarnung(liste, [], {"andere"}).verwaiste_auftraege == 1

    def test_zaehlt_mehrfach_vergebene_namen(self) -> None:
        s = [
            Sitzungsspanne("a", name="Marga"),
            Sitzungsspanne("b", name="Marga"),
            Sitzungsspanne("c", name="Snorre"),
            Sitzungsspanne("d", name=""),
        ]

        assert fruehwarnung([], s, set()).namen_mehrfach == 1

    def test_zaehlt_lange_sitzungen(self) -> None:
        s = [
            Sitzungsspanne("kurz", beginn=JETZT - timedelta(hours=2), ende=JETZT),
            Sitzungsspanne("lang", beginn=JETZT - timedelta(hours=48), ende=JETZT),
        ]

        assert fruehwarnung([], s, set()).lange_sitzungen == 1


class TestEinstieg:
    def test_leerer_bestand_stuerzt_nicht_ab(self, tmp_path: Path) -> None:
        s = lade_statistik(tmp_path, [], jetzt=JETZT)

        assert s.leer is False  # die Tagesreihe steht auch ohne Daten
        assert s.tokens_gesamt == 0
        assert len(s.tage) == 14

    def test_sitzung_von_vor_dem_fenster_behaelt_ihre_dauer(self, tmp_path: Path) -> None:
        """Sonst waere jede alte Sitzung kuenstlich kurz.

        Die Spannen entstehen ueber ALLE Anfragen und werden erst danach auf
        das Fenster gefiltert - andersherum begaenne die Sitzung scheinbar am
        Fensterrand.
        """
        ziel = tmp_path / "projekt"
        ziel.mkdir()
        saetze = [
            {
                "type": "assistant",
                "timestamp": _iso(stunden),
                "sessionId": "alt",
                "cwd": "C:/x/repo",
                "message": {"usage": {"output_tokens": 1}},
            }
            # 40 Tage alt bis heute - der Beginn liegt weit vor dem Fenster.
            for stunden in (24 * 40, 1)
        ]
        (ziel / "a.jsonl").write_text(
            "\n".join(json.dumps(s) for s in saetze) + "\n", encoding="utf-8", newline="\n"
        )

        s = lade_statistik(tmp_path, [], jetzt=JETZT)

        [sitzung] = s.sitzungen
        assert sitzung.stunden == pytest.approx(24 * 40 - 1, abs=0.1)
