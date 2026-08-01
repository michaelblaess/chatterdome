"""Sprachdateien gegeneinander pruefen.

Eine Sprachdatei verrottet still: ein Schluessel fehlt, ein Platzhalter heisst
anders, ein Eintrag wird nie benutzt. Diese Tests fangen das, ohne die Texte
selbst zu bewerten.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from string import Formatter

QUELLE = Path(__file__).resolve().parents[1] / "src" / "claude_sanctuary"


def _laden(sprache: str) -> dict[str, str]:
    datei = resources.files("claude_sanctuary") / "locale" / f"{sprache}.json"
    werte = json.loads(datei.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in werte.items()}


def _platzhalter(vorlage: str) -> set[str]:
    return {feld for _, feld, _, _ in Formatter().parse(vorlage) if feld}


def _verwendete_schluessel() -> set[str]:
    muster = re.compile(r"""t\(\s*["']([a-z][a-z_0-9]*(?:\.[a-z_0-9]+)+)["']""")
    gefunden: set[str] = set()
    for datei in QUELLE.rglob("*.py"):
        gefunden |= set(muster.findall(datei.read_text(encoding="utf-8")))
    return gefunden


class TestSprachdateien:
    def test_gleiche_schluessel(self) -> None:
        de, en = _laden("de"), _laden("en")
        assert set(de) == set(en), f"Unterschied: {set(de) ^ set(en)}"

    def test_gleiche_platzhalter(self) -> None:
        de, en = _laden("de"), _laden("en")
        abweichung = {
            schluessel
            for schluessel in de
            if _platzhalter(de[schluessel]) != _platzhalter(en.get(schluessel, ""))
        }
        assert not abweichung, f"Platzhalter weichen ab: {abweichung}"

    def test_kein_verwendeter_schluessel_fehlt(self) -> None:
        de = _laden("de")
        # Schluessel, die dynamisch zusammengesetzt werden, kennt der Regex nicht.
        dynamisch = {"binding.", "tooltip.", "state."}
        fehlend = {
            schluessel
            for schluessel in _verwendete_schluessel()
            if schluessel not in de
            and not any(schluessel.startswith(p) for p in dynamisch)
        }
        assert not fehlend, f"Nicht uebersetzt: {sorted(fehlend)}"

    def test_deutsche_texte_haben_echte_umlaute(self) -> None:
        # Ersatzschreibung faellt hier auf, bevor sie im Fenster landet.
        verdaechtig = {"ue", "oe", "ae"}
        treffer = [
            schluessel
            for schluessel, wert in _laden("de").items()
            if any(f" {teil}" in f" {wert.lower()}" for teil in ("fuer ", "ueber ", "oeffn"))
            or any(wert.lower().startswith(teil) for teil in verdaechtig)
        ]
        assert not treffer, f"Ersatzschreibung statt Umlaut: {treffer}"
