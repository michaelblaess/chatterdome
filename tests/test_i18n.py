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

from chatterdome.i18n import format_number

QUELLE = Path(__file__).resolve().parents[1] / "src" / "chatterdome"

ZUSAMMENGESETZT = (
    "binding.",
    "tooltip.",
    "state.",
    "quick.",
    "settings.update_",
    "mem.health.",
    # Die drei Filterlisten des Bus-Tabs bauen ihre Beschriftungen aus den
    # Schluesseln in busansicht.py zusammen.
    "bus.range.",
    "bus.group.",
    "bus.bind.",
)
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
    datei = resources.files("chatterdome") / "locale" / f"{sprache}.json"
    werte = json.loads(datei.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in werte.items()}


def _platzhalter(vorlage: str) -> set[str]:
    return {feld for _, feld, _, _ in Formatter().parse(vorlage) if feld}


def _quelldateien() -> list[Path]:
    """Alle Dateien, in denen ein Sprachschluessel stehen kann.

    Seit der Weboberflaeche sind das nicht mehr nur Python-Dateien: die
    Jinja-Vorlagen rufen ``t(...)`` genauso auf. Ohne sie meldet der Test jeden
    Web-Schluessel als tot, obwohl er im Browser angezeigt wird.
    """
    return [*QUELLE.rglob("*.py"), *QUELLE.rglob("*.html")]


def _verwendete_schluessel() -> set[str]:
    muster = re.compile(r"""t\(\s*["']([a-z][a-z_0-9]*(?:\.[a-z_0-9]+)+)["']""")
    gefunden: set[str] = set()
    for datei in _quelldateien():
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
        for datei in _quelldateien():
            gefunden |= set(muster.findall(datei.read_text(encoding="utf-8")))

        tot = {
            schluessel
            for schluessel in _laden("de")
            if schluessel not in gefunden
            and not schluessel.startswith(ZUSAMMENGESETZT)
            and schluessel not in ALTLAST
        }
        assert not tot, f"Nie verwendet: {sorted(tot)}"

    def test_deutsche_zahlen_haben_komma_und_punkt(self) -> None:
        """Dezimaltrenner Komma, Tausendertrenner Punkt - genau andersherum
        als Python es formatiert.

        Im Fenster stand "96.7 % aus dem Cache", und das ist im Deutschen
        schlicht falsch. Der Tauschschritt muss ueber ein Platzhalterzeichen
        laufen, sonst ueberschreibt die zweite Ersetzung die erste und aus
        1.234,5 wird 1,234,5.
        """
        assert format_number(96.7, 1, "de") == "96,7"
        # Kein x.x5 als Pruefwert: 7194,15 liegt binaer knapp darunter und
        # rundet ab. Der Testwert soll die Formatierung pruefen, nicht die
        # Gleitkommadarstellung.
        assert format_number(7194.16, 1, "de") == "7.194,2"
        assert format_number(17861, 0, "de") == "17.861"

    def test_englische_zahlen_bleiben_englisch(self) -> None:
        assert format_number(7194.16, 1, "en") == "7,194.2"

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
