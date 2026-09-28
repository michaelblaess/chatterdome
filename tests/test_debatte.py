"""Der Moderator der Diskussion, gegen eine Attrappe statt echter Sitzungen."""

from __future__ import annotations

import threading

from claude_sanctuary.kern.debatte import (
    Diskussion,
    Teilnehmer,
    als_markdown,
    anweisung,
    moderieren,
    zusammenfassen,
    zusammenfassung_auftrag,
)


class Uhr:
    """Eine Uhr, die nur beim Schlafen weiterlaeuft."""

    def __init__(self) -> None:
        self.stand = 0.0

    def __call__(self) -> float:
        return self.stand

    def schlafen(self, sekunden: float) -> None:
        self.stand += sekunden


class Attrappe:
    """Antwortet je Name nach einem Muster: Text, Fehlercode, Schweigen oder Sendefehler."""

    def __init__(self, verhalten: dict[str, str] | None = None) -> None:
        self.verhalten = verhalten or {}
        self.gesendet: list[tuple[str, str]] = []
        self.gelesen: dict[str, int] = {}

    def senden(self, an: str, text: str) -> tuple[str, str]:
        if self.verhalten.get(an) == "unerreichbar":
            return "", "Ziel nicht gefunden"
        kennung = f"k{len(self.gesendet)}"
        self.gesendet.append((an, text))
        return kennung, ""

    def antwort(self, an: str, kennung: str) -> tuple[int | None, str]:
        art = self.verhalten.get(an, "spricht")
        # Die erste Abfrage liefert nichts - wie im echten Bus, wo die
        # Antwort erst nach einer Weile kommt.
        self.gelesen[kennung] = self.gelesen.get(kennung, 0) + 1
        if self.gelesen[kennung] < 2 or art == "schweigt":
            return None, ""
        if art == "lehnt_ab":
            return 409, "stecke in etwas anderem"
        return 200, f"{an} sagt etwas zu {kennung}"


def _diskussion(**werte: object) -> Diskussion:
    teilnehmer = [Teilnehmer("Amalia", "verteidigt Angular"), Teilnehmer("Tamino"),
                  Teilnehmer("Kerstin")]
    basis: dict[str, object] = {"thema": "Ist Angular tot?", "teilnehmer": teilnehmer}
    basis.update(werte)
    return Diskussion(**basis)  # type: ignore[arg-type]


def _lauf(d: Diskussion, kanal: Attrappe, **werte: object) -> Diskussion:
    uhr = Uhr()
    return moderieren(d, kanal, uhr=uhr, schlafen=uhr.schlafen, **werte)  # type: ignore[arg-type]


class TestReihenfolge:
    def test_reihum_je_runde_und_danach_schlussworte(self) -> None:
        kanal = Attrappe()
        d = _lauf(_diskussion(runden=2), kanal)
        redner = [an for an, _ in kanal.gesendet]
        assert redner == ["Amalia", "Tamino", "Kerstin"] * 3
        assert [b.art for b in d.beitraege].count("beitrag") == 6
        assert [b.art for b in d.beitraege].count("schlusswort") == 3
        assert d.ende == "2 Runden gespielt"

    def test_immer_nur_einer_hat_das_wort(self) -> None:
        # Jede Anweisung geht an genau einen Empfaenger - keine Lawine.
        kanal = Attrappe()
        _lauf(_diskussion(runden=1), kanal)
        assert all(isinstance(an, str) for an, _ in kanal.gesendet)
        assert len(kanal.gesendet) == 6

    def test_verlauf_wandert_in_die_naechste_anweisung(self) -> None:
        kanal = Attrappe()
        _lauf(_diskussion(runden=1), kanal)
        zweite = kanal.gesendet[1][1]
        assert "[Amalia] Amalia sagt etwas zu k0" in zweite
        assert "Bisheriger Verlauf" not in kanal.gesendet[0][1]


class TestGrenzen:
    def test_zeit_beendet_vor_der_rundenzahl(self) -> None:
        kanal = Attrappe()
        # Jeder Beitrag kostet in der Attrappe einen Takt von 3 s, die Grenze
        # liegt bei 0,1 min = 6 s: nach zwei Rednern ist Schluss.
        d = _lauf(_diskussion(runden=10, dauer_minuten=0.1), kanal)
        assert d.ende.startswith("Zeit abgelaufen")
        assert [b.art for b in d.beitraege].count("beitrag") == 2
        assert [b.art for b in d.beitraege].count("schlusswort") == 3

    def test_stopp_von_hand_ohne_schlussworte(self) -> None:
        kanal = Attrappe()
        stopp = threading.Event()
        gesehen: list[str] = []

        def mitschreiben(beitrag: object) -> None:
            gesehen.append("x")
            if len(gesehen) == 2:
                stopp.set()

        d = _lauf(_diskussion(runden=5), kanal, stopp=stopp, beim_beitrag=mitschreiben)
        assert d.ende == "von Hand gestoppt"
        assert [b.art for b in d.beitraege].count("schlusswort") == 0
        assert len(d.beitraege) == 2


class TestFehlerfaelle:
    def test_schweigen_wird_als_ausgelassen_protokolliert(self) -> None:
        kanal = Attrappe({"Tamino": "schweigt"})
        d = _lauf(_diskussion(runden=1), kanal, frist=10.0)
        tamino = [b for b in d.beitraege if b.name == "Tamino"]
        assert tamino[0].art == "ausgelassen"
        assert "keine Antwort nach 10 s" in tamino[0].text

    def test_fehlercode_steht_im_protokoll(self) -> None:
        kanal = Attrappe({"Kerstin": "lehnt_ab"})
        d = _lauf(_diskussion(runden=1), kanal)
        kerstin = next(b for b in d.beitraege if b.name == "Kerstin")
        assert kerstin.art == "fehler"
        assert "409" in kerstin.text

    def test_unerreichbar_faellt_aus_der_reihe(self) -> None:
        kanal = Attrappe({"Tamino": "unerreichbar"})
        d = _lauf(_diskussion(runden=2), kanal)
        assert [an for an, _ in kanal.gesendet].count("Tamino") == 0
        assert [b.name for b in d.beitraege if b.art == "fehler"] == ["Tamino"]

    def test_zu_wenige_erreichbar_beendet(self) -> None:
        kanal = Attrappe({"Tamino": "unerreichbar", "Kerstin": "unerreichbar"})
        d = _lauf(_diskussion(runden=3), kanal)
        assert d.ende == "weniger als zwei Teilnehmer erreichbar"


class TestPruefung:
    def test_ohne_thema_startet_nichts(self) -> None:
        kanal = Attrappe()
        d = _lauf(_diskussion(thema="  "), kanal)
        assert d.ende == "Es fehlt ein Thema."
        assert kanal.gesendet == []

    def test_ein_teilnehmer_reicht_nicht(self) -> None:
        d = _diskussion(teilnehmer=[Teilnehmer("Amalia")])
        assert "mindestens zwei" in d.pruefen()

    def test_doppelter_teilnehmer(self) -> None:
        d = _diskussion(teilnehmer=[Teilnehmer("Amalia"), Teilnehmer("amalia")])
        assert "doppelt" in d.pruefen()


class TestSeiten:
    def test_ohne_vorgabe_abwechselnd_pro_und_contra(self) -> None:
        d = _diskussion()
        d.seiten_verteilen()
        assert [t.seite for t in d.teilnehmer] == ["pro", "contra", "pro"]

    def test_vorgegebene_seite_bekommt_ihren_gegenpart(self) -> None:
        d = _diskussion(teilnehmer=[Teilnehmer("Amalia", seite="contra"), Teilnehmer("Tamino")])
        d.seiten_verteilen()
        assert [t.seite for t in d.teilnehmer] == ["contra", "pro"]

    def test_nur_eine_seite_startet_nicht(self) -> None:
        kanal = Attrappe()
        teilnehmer = [Teilnehmer("Amalia", seite="pro"), Teilnehmer("Tamino", seite="pro")]
        d = _lauf(_diskussion(teilnehmer=teilnehmer), kanal)
        assert "PRO- und eine CONTRA" in d.ende
        assert kanal.gesendet == []

    def test_unbekannte_seite(self) -> None:
        d = _diskussion(teilnehmer=[Teilnehmer("Amalia", seite="dafuer"), Teilnehmer("Tamino")])
        assert "Unbekannte Seite" in d.pruefen()

    def test_anweisung_nennt_seite_und_gegenseite(self) -> None:
        d = _diskussion()
        d.seiten_verteilen()
        text = anweisung(d, d.teilnehmer[1], 1, schluss=False)
        assert "Deine Seite ist CONTRA" in text
        assert "Gegenseite: Amalia, Kerstin." in text

    def test_team_diskussion_kennt_keine_seiten(self) -> None:
        d = _diskussion(format="team")
        d.seiten_verteilen()
        assert all(t.seite == "" for t in d.teilnehmer)
        assert "Deine Seite" not in anweisung(d, d.teilnehmer[0], 1, schluss=False)


class TestRecherche:
    def test_ohne_recherche_keine_vorbereitung(self) -> None:
        kanal = Attrappe()
        _lauf(_diskussion(runden=1), kanal)
        assert not any("Vorbereitung" in text.splitlines()[0] for _, text in kanal.gesendet)

    def test_vorbereitung_parallel_vor_runde_eins(self) -> None:
        kanal = Attrappe()
        d = _lauf(_diskussion(runden=1, recherche=True), kanal)
        # Erst alle drei Vorbereitungen, dann erst die erste Runde.
        koepfe = [text.splitlines()[0] for _, text in kanal.gesendet]
        assert all(k.startswith("Diskussion, Vorbereitung") for k in koepfe[:3])
        assert koepfe[3].startswith("Diskussion, Runde 1")
        assert [b.art for b in d.beitraege][:3] == ["vorbereitung"] * 3

    def test_eigene_notizen_nur_beim_eigenen_redner(self) -> None:
        kanal = Attrappe()
        _lauf(_diskussion(runden=1, recherche=True), kanal)
        an_amalia = next(t for an, t in kanal.gesendet[3:] if an == "Amalia")
        an_tamino = next(t for an, t in kanal.gesendet[3:] if an == "Tamino")
        assert "Amalia sagt etwas zu k0" in an_amalia
        # Tamino sieht Amalias Beitrag aus Runde 1, aber nie ihre Notiz k0.
        assert "Amalia sagt etwas zu k0" not in an_tamino

    def test_schweigen_in_der_vorbereitung_haelt_nicht_auf(self) -> None:
        kanal = Attrappe({"Tamino": "schweigt"})
        d = _lauf(_diskussion(runden=1, recherche=True), kanal, frist=10.0,
                  frist_recherche=30.0)
        vorbereitung = [b for b in d.beitraege if b.runde == 0]
        assert {b.name: b.art for b in vorbereitung}["Tamino"] == "ausgelassen"
        assert any(b.art == "beitrag" for b in d.beitraege)


class TestZusammenfassung:
    def test_auftrag_enthaelt_verlauf_aber_keine_recherche(self) -> None:
        d = _lauf(_diskussion(runden=1, recherche=True), Attrappe())
        auftrag = zusammenfassung_auftrag(d)
        assert "[Amalia, Runde 1] Amalia sagt etwas zu k3" in auftrag
        assert "k0" not in auftrag   # Amalias Recherche-Notiz
        assert "Teilnehmer: Amalia (PRO)" in auftrag
        assert "niemanden zum Sieger" in auftrag

    def test_ergebnis_landet_im_protokoll(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        assert zusammenfassen(d, lambda _auftrag: ("  Beide Seiten ...  ", "")) == ""
        assert d.zusammenfassung == "Beide Seiten ..."
        assert "## Zusammenfassung\n\nBeide Seiten ..." in als_markdown(d)

    def test_fehler_des_modells_wird_gemeldet(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        assert zusammenfassen(d, lambda _auftrag: ("", "Zeitueberschreitung")) == (
            "Zeitueberschreitung"
        )
        assert d.zusammenfassung == ""
        assert "## Zusammenfassung" not in als_markdown(d)

    def test_leere_antwort_ist_ein_fehler(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        assert "leere" in zusammenfassen(d, lambda _auftrag: ("   ", ""))

    def test_ohne_beitraege_kein_aufruf(self) -> None:
        aufrufe: list[str] = []
        d = _diskussion()

        def modell(auftrag: str) -> tuple[str, str]:
            aufrufe.append(auftrag)
            return "x", ""

        assert "keine Beiträge" in zusammenfassen(d, modell)
        assert aufrufe == []


class TestAngabenImKurzbefehl:
    def test_seite_mit_und_ohne_rolle(self) -> None:
        from claude_sanctuary.debatte_cli import _haltung

        assert _haltung("pro") == ("pro", "")
        assert _haltung("Contra:Architektin") == ("contra", "Architektin")
        assert _haltung("stellt Fragen") == ("", "stellt Fragen")
        assert _haltung("-") == ("", "")


class TestAusgabe:
    def test_anweisung_ist_deterministisch(self) -> None:
        d = _diskussion()
        eins = anweisung(d, d.teilnehmer[0], 1, schluss=False)
        assert eins == anweisung(d, d.teilnehmer[0], 1, schluss=False)
        assert "Deine Rolle: verteidigt Angular" in eins
        assert "200-Quittung" in eins

    def test_markdown_nennt_beitraege_und_ende(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        text = als_markdown(d)
        assert text.startswith("# Ist Angular tot?")
        assert "**Amalia** (Runde 1" in text
        assert "_Ende: 1 Runde gespielt_" in text
