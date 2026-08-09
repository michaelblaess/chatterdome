"""Tests der Kern-Modelle."""

from __future__ import annotations

from datetime import datetime, timedelta

from claude_sanctuary.kern.modelle import (
    KONTEXT_ENG,
    KONTEXT_KRITISCH,
    VERWAIST_STUNDEN,
    Agent,
    Ampel,
    Bestand,
    geteilte_namen,
)


def _agent(**felder: object) -> Agent:
    vorgabe: dict[str, object] = {"name": "Test", "status": "idle", "rechner": "HIER"}
    vorgabe.update(felder)
    return Agent(**vorgabe)  # type: ignore[arg-type]


class TestAmpel:
    """Eine Ampel hat drei Farben - und der Kontext gehoert nicht dazu."""

    def test_idle_ist_gruen(self) -> None:
        assert _agent(status="idle").ampel is Ampel.FREI

    def test_busy_ist_gelb(self) -> None:
        assert _agent(status="busy").ampel is Ampel.BESCHAEFTIGT

    def test_nicht_erreichbar_ist_rot(self) -> None:
        assert _agent(status="idle", erreichbar=False).ampel is Ampel.WEG

    def test_voller_kontext_bleibt_gruen(self) -> None:
        # Ein freier Agent mit vollem Kontext ist weiterhin frei - die
        # Warnung gehoert in die Kontextspalte, nicht in die Ampel.
        agent = _agent(status="idle", kontext=KONTEXT_KRITISCH + 1)
        assert agent.ampel is Ampel.FREI
        assert agent.kontext_kritisch


class TestKontext:
    def test_unter_der_grenze_ist_unauffaellig(self) -> None:
        agent = _agent(kontext=KONTEXT_ENG - 1)
        assert not agent.kontext_eng
        assert not agent.kontext_kritisch

    def test_grenze_zaehlt_als_eng(self) -> None:
        assert _agent(kontext=KONTEXT_ENG).kontext_eng

    def test_kritisch_ist_auch_eng(self) -> None:
        agent = _agent(kontext=KONTEXT_KRITISCH)
        assert agent.kontext_eng
        assert agent.kontext_kritisch


class TestBestand:
    def test_summen(self) -> None:
        bestand = Bestand(
            rechner="HIER",
            zeit="",
            agenten=[
                _agent(name="A", status="busy", post=2, tokens=1000),
                _agent(name="B", status="idle", post=1, tokens=500),
                _agent(name="C", status="idle", erreichbar=False),
            ],
        )
        assert bestand.beschaeftigt == 1
        assert bestand.offene_auftraege == 3
        assert bestand.tokens == 1500

    def test_leerer_bestand(self) -> None:
        bestand = Bestand(rechner="HIER", zeit="")
        assert bestand.beschaeftigt == 0
        assert bestand.offene_auftraege == 0
        assert bestand.tokens == 0


class TestVerwaist:
    """Eine Sitzung, die laeuft, aber seit einem Tag nichts mehr tut.

    Anlass ist eine Petra auf RAINBOW, die am 09.08.2026 seit 151 Stunden lief
    und zuletzt vor fuenf Tagen aktiv war.
    """

    def _mit_alter(self, stunden: float, **felder: object) -> Agent:
        zeit = datetime.now().astimezone() - timedelta(hours=stunden)
        return _agent(letzte_zeit=zeit.isoformat(), **felder)

    def test_frische_aktivitaet_ist_nicht_verwaist(self) -> None:
        assert self._mit_alter(1).verwaist() is False

    def test_knapp_unter_der_frist_ist_nicht_verwaist(self) -> None:
        assert self._mit_alter(VERWAIST_STUNDEN - 0.5).verwaist() is False

    def test_ueber_der_frist_ist_verwaist(self) -> None:
        assert self._mit_alter(VERWAIST_STUNDEN + 0.5).verwaist() is True

    def test_der_gemeldete_fall_faellt_auf(self) -> None:
        assert self._mit_alter(5 * 24).verwaist() is True

    def test_ohne_zeitstempel_wird_nichts_behauptet(self) -> None:
        """Eine frisch gestartete Sitzung hat noch keinen Transkript-Eintrag."""
        assert _agent(letzte_zeit="").verwaist() is False

    def test_unlesbarer_zeitstempel_wird_nichts_behauptet(self) -> None:
        assert _agent(letzte_zeit="gestern").verwaist() is False

    def test_unerreichbar_zaehlt_nicht_als_verwaist(self) -> None:
        """Das sagt schon die Ampel - zwei Aussagen fuer dasselbe verwirren."""
        alt = self._mit_alter(5 * 24, erreichbar=False)
        assert alt.ampel is Ampel.WEG
        assert alt.verwaist() is False

    def test_bezugszeit_ist_uebergebbar(self) -> None:
        """Ohne das haengt der Test an der Uhr und wird irgendwann flatterhaft."""
        fest = datetime(2026, 8, 9, 12, 0).astimezone()
        a = _agent(letzte_zeit=(fest - timedelta(hours=30)).isoformat())
        assert a.verwaist(jetzt=fest) is True
        assert a.verwaist(jetzt=fest - timedelta(hours=10)) is False


class TestGeteilteNamen:
    """Derselbe Name auf zwei Rechnern ist erlaubt - er muss nur auffallen."""

    def test_der_gemeldete_fall(self) -> None:
        agenten = [
            _agent(name="Petra", rechner="RAINBOW"),
            _agent(name="Petra", rechner="SENZA"),
            _agent(name="Wolfram", rechner="RAINBOW"),
        ]
        assert geteilte_namen(agenten) == {"petra"}

    def test_ein_name_auf_einem_rechner_ist_nicht_geteilt(self) -> None:
        assert geteilte_namen([_agent(name="Petra", rechner="RAINBOW")]) == set()

    def test_zwei_sitzungen_auf_DEMSELBEN_rechner_zaehlen_nicht(self) -> None:
        """Dort verhindert der Pool die Dopplung - ein Treffer waere ein
        anderer Fehler und gehoert nicht in diese Anzeige."""
        agenten = [
            _agent(name="Petra", rechner="RAINBOW"),
            _agent(name="Petra", rechner="RAINBOW"),
        ]
        assert geteilte_namen(agenten) == set()

    def test_schreibweise_von_name_und_rechner_ist_egal(self) -> None:
        agenten = [
            _agent(name="Petra", rechner="rainbow"),
            _agent(name="petra", rechner="RAINBOW"),
            _agent(name="PETRA", rechner="senza"),
        ]
        assert geteilte_namen(agenten) == {"petra"}

    def test_namenlose_eintraege_stoeren_nicht(self) -> None:
        assert geteilte_namen([_agent(name=""), _agent(name="")]) == set()

    def test_leere_liste(self) -> None:
        assert geteilte_namen([]) == set()
