"""Darstellung der Agenten-Tabelle.

Zwei Befunde vom 09.08.2026, beide von Michael gemeldet:

* ``Petra`` lief gleichzeitig auf RAINBOW und SENZA. Das ist erlaubt - der Name
  ist eine Pacht pro Rechner. Die Tabelle muss aber zeigen, dass der blosse
  Name als Adresse nicht mehr reicht.
* Dieselbe Petra auf RAINBOW lief seit 151 Stunden und war zuletzt vor fuenf
  Tagen aktiv. Solche verwaisten Sitzungen sollen auffallen.

Geprueft wird die Zeile direkt statt ueber die laufende Oberflaeche: der
Aufbau der Zeile ist die Aussage, und ohne App bleibt der Test schnell.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from claude_sanctuary.kern.modelle import Agent, kennung
from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenTabelle


def _agent(**felder: object) -> Agent:
    vorgabe: dict[str, object] = {"name": "Petra", "status": "idle", "rechner": "RAINBOW"}
    vorgabe.update(felder)
    return Agent(**vorgabe)  # type: ignore[arg-type]


def _zeile(a: Agent, geteilt: set[str] | None = None) -> list[str]:
    tabelle = AgentenTabelle()
    tabelle._geteilt = geteilt or set()
    return [str(zelle) for zelle in tabelle._zeile(a)]


NAME = 1
ZEIT = AgentenTabelle._ZEIT_SPALTE
KONTEXT = AgentenTabelle._KONTEXT_SPALTE


class TestGeteilterName:
    def test_eindeutiger_name_bleibt_blank(self) -> None:
        assert _zeile(_agent())[NAME] == "Petra"

    def test_geteilter_name_wird_qualifiziert(self) -> None:
        """Genau die Form, mit der man ihn dann auch adressiert."""
        assert _zeile(_agent(), geteilt={"petra"})[NAME] == "Petra@RAINBOW"

    def test_der_rechner_steht_gross_da(self) -> None:
        zeile = _zeile(_agent(rechner="senza"), geteilt={"petra"})
        assert zeile[NAME] == "Petra@SENZA"

    def test_eigene_sitzung_behaelt_ihren_stern(self) -> None:
        zeile = _zeile(_agent(selbst=True), geteilt={"petra"})
        assert zeile[NAME] == "Petra@RAINBOW *"


class TestVerwaistMarkiert:
    def _alt(self, stunden: float) -> Agent:
        zeit = datetime.now().astimezone() - timedelta(hours=stunden)
        return _agent(letzte_zeit=zeit.isoformat())

    def test_frische_sitzung_ohne_warnzeichen(self) -> None:
        assert "⚠" not in _zeile(self._alt(2))[ZEIT]

    def test_verwaiste_sitzung_bekommt_das_warnzeichen(self) -> None:
        zeile = _zeile(self._alt(5 * 24))
        assert zeile[ZEIT].startswith("⚠")
        assert "5 d" in zeile[ZEIT]

    def test_ohne_zeitstempel_kein_warnzeichen(self) -> None:
        """Eine gerade gestartete Sitzung ist nicht tot, nur neu."""
        zeile = _zeile(_agent(letzte_zeit=""))
        assert "⚠" not in zeile[ZEIT]
        assert zeile[ZEIT] == "-"

    def test_unerreichbar_bekommt_kein_zweites_zeichen(self) -> None:
        """Das sagt schon die Ampel in Spalte 0."""
        alt = self._alt(5 * 24)
        alt.erreichbar = False
        assert "⚠" not in _zeile(alt)[ZEIT]


class TestAuswahlBleibtBeimRichtigen:
    """Der gemeldete Fehler vom 09.08.2026.

    Michael waehlte Petra@SENZA, schickte einen Auftrag - und beim naechsten
    Neuaufbau sprang die Markierung auf Petra@RAINBOW. Der naechste Auftrag
    ging damit an die falsche Sitzung. Der Fehler verstaerkte sich selbst,
    weil die Liste nach offener Post sortiert ist und die falsch belieferte
    Sitzung dadurch weiter nach oben rutschte.

    Ursache: die Tabelle merkte sich die Auswahl ueber den blossen NAMEN und
    nahm beim Wiederherstellen den ersten Treffer.
    """

    def test_kennung_trennt_gleiche_namen_auf_verschiedenen_rechnern(self) -> None:
        a = _agent(name="Petra", rechner="RAINBOW")
        b = _agent(name="Petra", rechner="SENZA")
        assert kennung(a) != kennung(b)

    def test_kennung_ist_unabhaengig_von_der_schreibweise(self) -> None:
        """Sonst verliert die Auswahl ihren Halt, sobald eine Quelle den
        Rechner klein schreibt."""
        assert kennung(_agent(name="Petra", rechner="senza")) == kennung(
            _agent(name="petra", rechner="SENZA")
        )

    def test_kennung_haengt_nicht_an_der_session_id(self) -> None:
        """Die aendert sich beim Fortsetzen - die Auswahl darf das nicht."""
        vorher = _agent(session_id="alt-1")
        nachher = _agent(session_id="neu-2")
        assert kennung(vorher) == kennung(nachher)

    def test_kennung_ueberlebt_die_veraenderlichen_felder(self) -> None:
        """Post und Kontext aendern sich im Sekundentakt."""
        assert kennung(_agent(post=0, kontext=1)) == kennung(_agent(post=3, kontext=99))


class TestWarnzellenBlinken:
    """Michael am 28.09.2026: verwaiste Sitzungen und kritischer Kontext sollen blinken.

    Geblinkt wird von Hand im Takt (ANSI-blink ignoriert Windows Terminal), und
    nur die Warnzellen werden per update_cell umgefaerbt - die Tabelle wird
    dabei nicht neu aufgebaut.
    """

    async def test_nur_warnzellen_wechseln_die_farbe(self) -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import DataTable

        from claude_sanctuary.kern.modelle import KONTEXT_KRITISCH

        class NurTabelle(App[None]):
            def compose(self) -> ComposeResult:
                yield AgentenTabelle(id="agenten")

        alt = (datetime.now().astimezone() - timedelta(days=4)).isoformat()
        frisch = datetime.now().astimezone().isoformat()
        app = NurTabelle()
        async with app.run_test(size=(200, 20)) as pilot:
            widget = app.query_one("#agenten", AgentenTabelle)
            widget.uebernehmen([
                _agent(name="Luzie", letzte_zeit=alt),
                _agent(name="Therese", letzte_zeit=frisch, kontext=KONTEXT_KRITISCH + 6000),
                _agent(name="Ruhig", letzte_zeit=frisch, kontext=1000),
            ])
            await pilot.pause()
            tabelle = app.query_one("#agenten-daten", DataTable)

            def stile() -> dict[str, tuple[str, str]]:
                ergebnis = {}
                for i, a in enumerate(widget._sichtbar):
                    zeile = tabelle.get_row_at(i)
                    ergebnis[a.name] = (str(zeile[ZEIT].style), str(zeile[KONTEXT].style))
                return ergebnis

            vorher = stile()
            widget._blinken()
            await pilot.pause()
            nachher = stile()
            assert "on #e74c3c" in nachher["Luzie"][0], nachher
            assert "on #e74c3c" in nachher["Therese"][1], nachher
            assert nachher["Ruhig"] == vorher["Ruhig"], "eine ruhige Zeile blinkt nicht"
            widget._blinken()
            await pilot.pause()
            assert stile() == vorher, "der zweite Takt stellt die Grundfarbe wieder her"
