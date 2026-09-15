"""Den Statistik-Tab headless fahren.

Geprueft wird die Verdrahtung, nicht die Auswertung - die steht in
test_statistik.py. Die Transkripte kommen aus einem eigenen Verzeichnis: der
echte Bestand unter ~/.claude/projects ist 369 MB gross und haengt davon ab,
wer den Test gerade startet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from textual.widgets import Static
from textual_plotext import PlotextPlot

from claude_sanctuary.kern.modelle import Auftrag, Bestand, Busbestand, Ereignis, Namenspool
from claude_sanctuary.kern.statistik import lade_statistik as echte_auswertung
from claude_sanctuary.tui import app as app_modul
from claude_sanctuary.tui.app import SanctuaryApp

JETZT = datetime.now(UTC)


def _iso(stunden_vorher: float) -> str:
    return (JETZT - timedelta(hours=stunden_vorher)).isoformat().replace("+00:00", "Z")


BUS = Busbestand(
    rechner="TESTHOST",
    verfall_stunden=24,
    auftraege=[
        Auftrag(
            auftrag_id="offen",
            zustand="submitted",
            von="Sanctuary",
            an="Marga",
            erstellt=_iso(3),
            geaendert=_iso(3),
            an_session="",
            bindung="rolle",
            verlauf=[Ereignis(art="auftrag", ts=_iso(3))],
        )
    ],
)


class StilleQuelle:
    """Keine Unterprozesse - hier geht es nur um den Statistik-Tab."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        return Bestand(rechner="TESTHOST", zeit="")

    def namen(self) -> Namenspool:
        return Namenspool()

    def verlauf(self, name: str, *, session_id: str = "", seit: str = "") -> list[object]:
        return []

    def bestandsverlauf(self, grenze: int = 0) -> Busbestand:
        return BUS


@pytest.fixture
def projekte(tmp_path: Path) -> Path:
    """Zwei Sitzungen, die sich ueberlappen - sonst waere die Flotte immer 1."""
    wurzel = tmp_path / "projects"
    (wurzel / "repo").mkdir(parents=True)
    for kennung, stunden in (("s1", (5.0, 1.0)), ("s2", (4.0, 0.5))):
        saetze: list[dict[str, object]] = [
            {"type": "agent-name", "agentName": f"Marga · {kennung}", "sessionId": kennung}
        ]
        saetze += [
            {
                "type": "assistant",
                "timestamp": _iso(vor),
                "sessionId": kennung,
                "cwd": "C:/Repos/claude-sanctuary",
                "message": {
                    "usage": {
                        "input_tokens": 1000,
                        "cache_read_input_tokens": 40000,
                        "output_tokens": 500,
                    }
                },
            }
            for vor in stunden
        ]
        (wurzel / "repo" / f"{kennung}.jsonl").write_text(
            "\n".join(json.dumps(s) for s in saetze) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return wurzel


@pytest.fixture
def app(projekte: Path, monkeypatch: pytest.MonkeyPatch) -> SanctuaryApp:
    # Ohne diese Ersatzfunktion liest der Test die ECHTEN Transkripte unter
    # ~/.claude/projects - hunderte Megabyte, abhaengig vom Rechner.
    monkeypatch.setattr(
        app_modul,
        "lade_statistik",
        lambda _pfad, auftraege=None, **rest: echte_auswertung(projekte, auftraege, **rest),
    )
    gebaut = SanctuaryApp(quelle=StilleQuelle())
    monkeypatch.setattr(gebaut, "_frage_disclaimer", lambda: None)
    return gebaut


async def _oeffnen(pilot: object, app: SanctuaryApp) -> None:
    await pilot.press("k")  # type: ignore[attr-defined]
    for _ in range(300):
        await pilot.pause()  # type: ignore[attr-defined]
        if app._statistik is not None:
            break
    for _ in range(20):
        await pilot.pause()  # type: ignore[attr-defined]


class TestTab:
    async def test_taste_k_oeffnet_den_tab_und_rechnet(self, app: SanctuaryApp) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            assert app.query_one("#bereiche").active == "tab-statistik"
            assert app._statistik is not None
            assert app._statistik.anfragen_gesamt == 4

    async def test_alle_sechs_sektionen_stehen(self, app: SanctuaryApp) -> None:
        async with app.run_test(size=(200, 60)) as pilot:
            await _oeffnen(pilot, app)

            for kennung in ("#stats-parallel", "#stats-verbrauch", "#stats-dauer", "#stats-bus"):
                assert app.query_one(kennung, PlotextPlot).size.height > 0, kennung
            # Ordner und Fruehwarnung sind Text, kein Diagramm - siehe
            # statistik_dashboard._ordner.
            assert str(app.query_one("#stats-ordner", Static).content).strip()
            assert app.query_one("#stats-warnung", Static)

    async def test_kopfzeile_nennt_cache_anteil_und_spitze(self, app: SanctuaryApp) -> None:
        async with app.run_test(size=(200, 60)) as pilot:
            await _oeffnen(pilot, app)

            text = str(app.query_one("#stats-kopf", Static).content)
            # Zwei sich ueberlappende Sitzungen - die Spitze MUSS zwei sein,
            # sonst rechnet der Intervall-Sweep nicht mit.
            assert "2" in text
            assert "%" in text

    async def test_diagramme_tragen_daten(self, app: SanctuaryApp) -> None:
        """Ein leeres Diagramm sieht aus wie ein gefuelltes ohne Werte."""
        async with app.run_test(size=(200, 60)) as pilot:
            await _oeffnen(pilot, app)

            gebaut = app.query_one("#stats-verbrauch", PlotextPlot).plt.build()
            assert "█" in gebaut

    async def test_warnung_meldet_den_vererbbaren_auftrag(self, app: SanctuaryApp) -> None:
        async with app.run_test(size=(200, 60)) as pilot:
            await _oeffnen(pilot, app)

            assert app._statistik is not None
            assert app._statistik.warnung.vererbbar_offen == 1
            assert str(app.query_one("#stats-warnung", Static).content).strip()

    async def test_ohne_transkripte_kein_absturz(
        self, app: SanctuaryApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Bewusst die urspruengliche Funktion und nicht app_modul.lade_statistik:
        # die zeigt an dieser Stelle schon auf die Ersatzfunktion der Fixture,
        # und der Test haette weiter deren Transkripte gelesen.
        leer = tmp_path / "leer"
        monkeypatch.setattr(
            app_modul,
            "lade_statistik",
            lambda _pfad, auftraege=None, **rest: echte_auswertung(leer, auftraege, **rest),
        )
        async with app.run_test(size=(200, 60)) as pilot:
            await _oeffnen(pilot, app)

            assert app._statistik is not None
            assert app._statistik.anfragen_gesamt == 0
