"""Der Moderator der Diskussion, gegen eine Attrappe statt echter Sitzungen."""

from __future__ import annotations

import threading

import pytest

from chatterdome.kern.debatte import (
    STIMMUNGEN,
    Diskussion,
    Teilnehmer,
    Verbrauch,
    abgegebene_stimmen,
    absaetze,
    abstimmung,
    als_markdown,
    anweisung,
    hinweis_anhaengen,
    moderieren,
    vorbereitung,
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
        if art == "ohne_netz":
            # So meldet sich ein Agent, dessen Websuche gescheitert ist.
            return 200, f"KEINE RECHERCHE: classifier gave no verdict\n{an} zu {kennung}"
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
    def test_reihum_je_runde_und_auf_wunsch_schlussworte(self) -> None:
        kanal = Attrappe()
        d = _lauf(_diskussion(runden=2, schlussworte=True), kanal)
        redner = [an for an, _ in kanal.gesendet]
        assert redner == ["Amalia", "Tamino", "Kerstin"] * 3
        assert [b.art for b in d.beitraege].count("beitrag") == 6
        assert [b.art for b in d.beitraege].count("schlusswort") == 3
        assert d.ende == "2 Runden gespielt"

    def test_ohne_wunsch_keine_schlussworte(self) -> None:
        # Michael: "keine Zusammenfassungen im Chat" - Schlussworte waren genau das.
        kanal = Attrappe()
        d = _lauf(_diskussion(runden=2), kanal)
        assert len(kanal.gesendet) == 6
        assert "schlusswort" not in [b.art for b in d.beitraege]

    def test_immer_nur_einer_hat_das_wort(self) -> None:
        # Jede Anweisung geht an genau einen Empfaenger - keine Lawine.
        kanal = Attrappe()
        _lauf(_diskussion(runden=1, schlussworte=True), kanal)
        assert all(isinstance(an, str) for an, _ in kanal.gesendet)
        assert len(kanal.gesendet) == 6

    def test_beim_wort_meldet_jeden_redner_vorher(self) -> None:
        kanal = Attrappe()
        gerufen: list[tuple[str, int]] = []
        _lauf(_diskussion(runden=1), kanal,
              beim_wort=lambda redner, runde: gerufen.append((redner.name, runde)))
        assert gerufen == [("Amalia", 1), ("Tamino", 1), ("Kerstin", 1)]

    def test_beitrag_kennt_die_seite_seines_redners(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        assert [(b.name, b.seite) for b in d.beitraege] == [
            ("Amalia", "pro"), ("Tamino", "contra"), ("Kerstin", "pro")]

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
        d = _lauf(_diskussion(runden=10, dauer_minuten=0.1, schlussworte=True), kanal)
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


class TestGescheiterteRecherche:
    """Befund vom 28.09.2026: alle Suchaufrufe scheiterten, im Chat sah alles geprueft aus."""

    def test_vermerk_haengt_an_den_beitraegen_des_betroffenen(self) -> None:
        kanal = Attrappe({"Tamino": "ohne_netz"})
        d = _lauf(_diskussion(runden=1, recherche=True), kanal)
        tamino = next(t for t in d.teilnehmer if t.name == "Tamino")
        assert tamino.ohne_recherche == "classifier gave no verdict"
        runde = {b.name: b.ungeprueft for b in d.beitraege if b.art == "beitrag"}
        assert runde == {"Amalia": False, "Tamino": True, "Kerstin": False}
        notiz = next(b for b in d.beitraege if b.art == "vorbereitung" and b.name == "Tamino")
        assert "nicht live geprüft" in notiz.hinweis

    def test_schweigen_in_der_vorbereitung_zaehlt_als_ungeprueft(self) -> None:
        kanal = Attrappe({"Tamino": "schweigt"})
        d = _lauf(_diskussion(runden=1, recherche=True), kanal, frist=10.0, frist_recherche=30.0)
        assert next(t for t in d.teilnehmer if t.name == "Tamino").ohne_recherche

    def test_vorbereitung_bittet_um_zweiten_versuch_und_um_den_vermerk(self) -> None:
        d = _diskussion(recherche=True)
        text = vorbereitung(d, d.teilnehmer[0])
        assert "einmal erneut" in text
        assert "KEINE RECHERCHE" in text


class TestPositionen:
    def test_benannte_positionen_statt_ja_und_nein(self) -> None:
        d = _diskussion(thema="Unity oder Godot?", positionen=("Unity", "Godot"))
        d.seiten_verteilen()
        text = anweisung(d, d.teilnehmer[1], 1, schluss=False)
        assert 'Deine Antwort auf die Frage: "Godot".' in text
        assert 'Gegenantwort "Unity" vertritt Amalia, Kerstin.' in text
        assert "mit Ja" not in text

    def test_ohne_namen_bleibt_es_bei_ja_und_nein(self) -> None:
        d = _diskussion()
        assert d.position("pro") == "Ja"
        assert d.position("contra") == "Nein"

    def test_anweisung_verlangt_ein_gespraech_und_kein_referat(self) -> None:
        d = _diskussion()
        d.seiten_verteilen()
        text = anweisung(d, d.teilnehmer[0], 1, schluss=False)
        assert "genau EIN Argument" in text
        assert "Kein Fazit, keine Zusammenfassung" in text
        assert "Höchstens 80 Wörter" in text


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
        from chatterdome.debatte_cli import _haltung

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


class TestFortsetzen:
    def test_geht_nach_der_letzten_runde_weiter_ohne_neue_vorbereitung(self) -> None:
        kanal = Attrappe()
        d = _lauf(_diskussion(runden=2, recherche=True), kanal)
        assert d.gespielte_runden == 2
        vorbereitungen = sum(1 for b in d.beitraege if b.art == "vorbereitung")
        d.runden = d.gespielte_runden + 1
        weiter = Attrappe()
        _lauf(d, weiter)
        assert [an for an, _ in weiter.gesendet] == ["Amalia", "Tamino", "Kerstin"]
        assert all("Runde 3 von 3" in text.splitlines()[0] for _, text in weiter.gesendet)
        assert sum(1 for b in d.beitraege if b.art == "vorbereitung") == vorbereitungen
        assert d.gespielte_runden == 3
        # Der alte Verlauf steht in der neuen Anweisung.
        assert "Amalia sagt etwas" in weiter.gesendet[0][1]

    def test_gespielte_runden_zaehlt_auch_ausgelassene(self) -> None:
        d = _lauf(_diskussion(runden=2), Attrappe({"Kerstin": "schweigt"}),
                  frist=10.0)
        assert d.gespielte_runden == 2


class TestAbsaetze:
    MARIA = ("Roundhouse und Signalbox vertragen sich gut, Agatha. Bei Chinwag widerspreche "
             "ich aber: Das Werkzeug plaudert doch nicht nur. Es verteilt Aufträge, verlangt "
             "Quittungen mit Statuscodes und kann eine Instanz sogar beenden. Ein Schwätzchen "
             "verniedlicht genau den Teil, auf den man sich verlassen muss. Wenn nachts ein "
             "Auftrag hängen bleibt, suchst Du den Fehler dann gern in einem Programm namens "
             "Schwätzchen? Catherder sagt wenigstens ehrlich, dass Koordination Arbeit ist.")

    def test_langer_beitrag_bricht_an_der_satzgrenze_nahe_der_mitte(self) -> None:
        # Genau dort hat Michael am 28.09.2026 den Umbruch markiert.
        erster, zweiter = absaetze(self.MARIA)
        assert erster.endswith("sogar beenden.")
        assert zweiter.startswith("Ein Schwätzchen")
        assert f"{erster} {zweiter}" == self.MARIA

    def test_kurzer_beitrag_bleibt_ein_absatz(self) -> None:
        assert absaetze("Kurz. Und knapp.") == ["Kurz. Und knapp."]

    def test_eigene_umbrueche_bleiben(self) -> None:
        assert absaetze("Erstens.\n\nZweitens.") == ["Erstens.", "Zweitens."]

    def test_abkuerzungen_teilen_nicht(self) -> None:
        text = " ".join(["Das gilt z. B. auch hier, wort"] * 10)
        assert absaetze(text) == [text]


class TestVerbrauch:
    def test_summe_und_anteile(self) -> None:
        v = Verbrauch(10, 100, 5) + Verbrauch(1, 2, 3)
        assert (v.neu, v.cache, v.aus) == (11, 102, 8)
        assert v.echt == 19 and v.gesamt == 121


class TestVorbereitungsSignal:
    def test_meldet_die_rechercheure_bevor_die_erste_notiz_kommt(self) -> None:
        gemeldet: list[list[str]] = []
        stand_beim_melden: list[int] = []
        d = _diskussion(runden=1, recherche=True)

        def melden(teilnehmer: list[Teilnehmer]) -> None:
            gemeldet.append([t.name for t in teilnehmer])
            stand_beim_melden.append(len(d.beitraege))

        _lauf(d, Attrappe({"Kerstin": "unerreichbar"}), beim_vorbereiten=melden)
        assert gemeldet == [["Amalia", "Tamino"]], "wer unerreichbar ist, recherchiert nicht"
        # Nur der Sendefehler von Kerstin steht vorher im Protokoll.
        assert stand_beim_melden == [1]

    def test_ohne_recherche_kein_signal(self) -> None:
        gemeldet: list[object] = []
        _lauf(_diskussion(runden=1), Attrappe(), beim_vorbereiten=gemeldet.append)
        assert gemeldet == []


class TestHinweisDesModerators:
    def test_hinweis_geht_an_die_naechsten_redner_und_zaehlt_keine_runde(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        hinweis_anhaengen(d, "  Parleyvoo ist in TMview frei.  ")
        hinweis_anhaengen(d, "   ")
        assert [b.art for b in d.beitraege].count("moderator") == 1
        assert d.gespielte_runden == 1
        d.runden = 2
        weiter = Attrappe()
        _lauf(d, weiter)
        anweisung_text = weiter.gesendet[0][1]
        assert "[Moderator] Parleyvoo ist in TMview frei." in anweisung_text
        assert "neue Informationen des Moderators" in anweisung_text
        assert "Runde 2 von 2" in anweisung_text.splitlines()[0]
        assert "[Moderator, neue Information] Parleyvoo" in zusammenfassung_auftrag(d)
        assert "> **Moderator**" in als_markdown(d)

    def test_ohne_hinweis_keine_erklaerung(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        d.runden = 2
        weiter = Attrappe()
        _lauf(d, weiter)
        assert "Moderator" not in weiter.gesendet[0][1].split("Bisheriger Verlauf:")[1]


class TestEndegrundInDerSprache:
    """Der Grund steht im Kopf der Diskussion, also in der Sprache der Oberflaeche.

    Bis zum 02.10.2026 kam er fest auf Deutsch aus dem Kern, in der englischen
    Oberflaeche stand "Finished: 2 Runden gespielt".
    """

    def test_englische_oberflaeche_bekommt_englischen_grund(self) -> None:
        from chatterdome import i18n

        i18n.load_locale("en")
        try:
            d = _lauf(_diskussion(runden=2), Attrappe())
            einzeln = _lauf(_diskussion(runden=1), Attrappe())
        finally:
            i18n.load_locale("de")
        assert d.ende == "2 rounds played"
        assert einzeln.ende == "1 round played"

    def test_ohne_geladene_sprache_gilt_die_deutsche_vorgabe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from chatterdome import i18n

        monkeypatch.setattr(i18n, "_strings", {})
        d = _lauf(_diskussion(runden=3), Attrappe())
        assert d.ende == "3 Runden gespielt"


class TestStimmung:
    def test_sachlich_setzt_nichts_dazu(self) -> None:
        d = _diskussion()
        d.seiten_verteilen()
        assert "Ton der Diskussion" not in anweisung(d, d.teilnehmer[0], 1, False)

    @pytest.mark.parametrize("stimmung", [s for s in STIMMUNGEN if s != "sachlich"])
    def test_jede_stimmung_steht_in_der_anweisung(self, stimmung: str) -> None:
        d = _diskussion(stimmung=stimmung)
        d.seiten_verteilen()
        assert STIMMUNGEN[stimmung] in anweisung(d, d.teilnehmer[0], 1, False)

    def test_unbekannte_stimmung_startet_nicht(self) -> None:
        assert "Unbekannte Stimmung" in _diskussion(stimmung="zynisch").pruefen()

    def test_die_zusammenfassung_bewertet_den_ton_nicht(self) -> None:
        d = _lauf(_diskussion(runden=1, stimmung="unfair"), Attrappe())
        assert "bewerte ihn nicht" in zusammenfassung_auftrag(d)
        assert "bewerte ihn nicht" not in zusammenfassung_auftrag(
            _lauf(_diskussion(runden=1), Attrappe()))


class TestEntscheidung:
    def test_ohne_haken_keine_abstimmung(self) -> None:
        d = _lauf(_diskussion(runden=1), Attrappe())
        assert "entscheidung" not in [b.art for b in d.beitraege]
        assert "Erkläre niemanden zum Sieger" in zusammenfassung_auftrag(d)

    def test_nach_den_runden_stimmt_jeder_einmal_ab(self) -> None:
        kanal = Attrappe()
        d = _lauf(_diskussion(runden=2, entscheidung=True), kanal)
        arten = [b.art for b in d.beitraege]
        assert arten == ["beitrag"] * 6 + ["entscheidung"] * 3
        assert [text.splitlines()[0] for _, text in kanal.gesendet[-3:]] == [
            "Diskussion, Abstimmung: Die Runden sind vorbei, jetzt wird entschieden."] * 3

    def test_die_zielvorgabe_steht_in_jeder_runde_und_zieht_in_der_letzten_an(self) -> None:
        d = _diskussion(runden=3, entscheidung=True)
        d.seiten_verteilen()
        erste = anweisung(d, d.teilnehmer[0], 1, False)
        letzte = anweisung(d, d.teilnehmer[0], 3, False)
        assert "Nach Runde 3 wird abgestimmt" in erste
        assert "Das ist die letzte Runde" not in erste
        assert "Das ist die letzte Runde" in letzte

    def test_wer_abstimmt_sieht_die_stimmen_der_anderen_nicht(self) -> None:
        kanal = Attrappe()
        d = _lauf(_diskussion(runden=1, entscheidung=True), kanal)
        erste_stimme = next(b for b in d.beitraege if b.art == "entscheidung")
        assert erste_stimme.text not in kanal.gesendet[-1][1]

    def test_in_der_abstimmung_legt_der_redner_seine_seite_ab(self) -> None:
        d = _diskussion(positionen=("Unity", "Godot"))
        d.seiten_verteilen()
        text = abstimmung(d, d.teilnehmer[0])
        assert "Leg diese Rolle jetzt ab" in text
        assert 'eine der beiden Antworten: "Unity" oder "Godot"' in text

    def test_pro_und_contra_antworten_auf_eine_frage(self) -> None:
        d = _diskussion(thema="Wird KI die Menschheit auslöschen?",
                        positionen=("Ja, und das ist gut so", "Nein, dafür ist sie zu bequem"))
        d.seiten_verteilen()
        text = anweisung(d, d.teilnehmer[0], 1, False)
        assert 'Frage: "Wird KI die Menschheit auslöschen?"' in text
        assert 'Deine Antwort auf die Frage: "Ja, und das ist gut so".' in text
        team = _diskussion(format="team")
        assert 'Thema: "Ist Angular tot?"' in anweisung(team, team.teilnehmer[0], 1, False)

    def test_im_team_ist_die_stimme_ein_vorschlag(self) -> None:
        d = _diskussion(format="team")
        text = abstimmung(d, d.teilnehmer[0])
        assert "Leg diese Rolle" not in text
        assert "der Vorschlag, den das Team umsetzen soll" in text

    def test_auch_nach_zeitablauf_aber_nicht_nach_stopp(self) -> None:
        zeit = _lauf(_diskussion(runden=10, dauer_minuten=0.1, entscheidung=True), Attrappe())
        assert [b.art for b in zeit.beitraege].count("entscheidung") == 3
        stopp = threading.Event()
        stopp.set()
        gestoppt = _lauf(_diskussion(runden=2, entscheidung=True), Attrappe(), stopp=stopp)
        assert "entscheidung" not in [b.art for b in gestoppt.beitraege]

    def test_die_zusammenfassung_nennt_das_ergebnis(self) -> None:
        d = _lauf(_diskussion(runden=1, entscheidung=True), Attrappe())
        auftrag = zusammenfassung_auftrag(d)
        assert 'der mit "Entscheidung:" beginnt' in auftrag
        assert "Erkläre niemanden zum Sieger" not in auftrag
        assert auftrag.count(", Abstimmung] ") == 3

    def test_nach_dem_fortsetzen_gelten_nur_die_neuen_stimmen(self) -> None:
        d = _lauf(_diskussion(runden=1, entscheidung=True), Attrappe())
        alte = abgegebene_stimmen(d)
        d.runden = 2
        d = _lauf(d, Attrappe())
        neue = abgegebene_stimmen(d)
        assert len(alte) == len(neue) == 3
        assert not any(a is n for a in alte for n in neue)
        # Die neuen Redner bekommen die alten Stimmen auch nicht als Verlauf.
        assert zusammenfassung_auftrag(d).count(", Abstimmung] ") == 3

    def test_das_protokoll_fuehrt_stimmen_und_stimmung(self) -> None:
        d = _lauf(_diskussion(runden=1, entscheidung=True, stimmung="fair"), Attrappe())
        text = als_markdown(d)
        assert "Stimmung: fair" in text
        assert text.count(", Abstimmung (") == 3
