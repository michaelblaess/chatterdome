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

ZUSAMMENGESETZT = ("binding.", "tooltip.", "state.", "quick.", "settings.update_", "mem.health.")
"""Praefixe, deren Schluessel zur Laufzeit gebaut werden.

Ermittelt aus allen ``t(f"...")``-Aufrufen im Quelltext. Wer einen neuen
dynamischen Schluessel einfuehrt, ergaenzt hier sein Praefix - sonst meldet
der Test ihn zu Recht als tot.
"""

ALTLAST = frozenset(
    {
        "app.subtitle",
        "head.account",
        "head.cache",
        "head.dbsize",
        "head.names",
        "head.net",
        "head.operation",
        "head.tech",
        "head.tokens",
        "log.refreshed",
        "log.unreachable",
        "start.dir",
        "start.name",
        "start.title",
        "tip.context",
        "tip.post",
        "tip.state",
        "tip.tokens",
        "tip.version",
    }
)
"""Schluessel, die schon vor dieser Pruefung niemand mehr abgerufen hat.

Sie stehen hier, damit der Test ab sofort fuer alles Neue greift, statt an
der Altlast zu scheitern und deshalb abgeschaltet zu werden. Die Liste ist
zum Schrumpfen da: wer einen Eintrag wieder verwendet oder loescht, nimmt ihn
hier heraus. Sie darf nicht wachsen.
"""


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

    def test_kein_schluessel_ist_unbenutzt(self) -> None:
        """Der wertvollste der vier Tests.

        Ein Schluessel, den niemand mehr abruft, faellt sonst nie auf - er
        wird in beiden Sprachen gepflegt und landet in jedem Uebersetzungslauf.
        Gesucht wird nach ALLEN schluesselfoermigen Zeichenketten im Quelltext,
        nicht nur nach t(...): Beschriftungen in BINDINGS und Schluessel in
        Variablen waeren sonst falsch als tot gemeldet.
        """
        muster = re.compile(r"""["']([a-z][a-z_0-9]*(?:\.[a-z_0-9]+)+)["']""")
        gefunden: set[str] = set()
        for datei in QUELLE.rglob("*.py"):
            gefunden |= set(muster.findall(datei.read_text(encoding="utf-8")))

        tot = {
            schluessel
            for schluessel in _laden("de")
            if schluessel not in gefunden
            and not schluessel.startswith(ZUSAMMENGESETZT)
            and schluessel not in ALTLAST
        }
        assert not tot, f"Nie verwendet: {sorted(tot)}"

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
