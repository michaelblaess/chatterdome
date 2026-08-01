"""Tests der Kern-Modelle."""

from __future__ import annotations

from claude_sanctuary.kern.modelle import (
    KONTEXT_ENG,
    KONTEXT_KRITISCH,
    Agent,
    Ampel,
    Bestand,
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
