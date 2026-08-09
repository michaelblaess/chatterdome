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

from claude_sanctuary.kern.modelle import Agent
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
