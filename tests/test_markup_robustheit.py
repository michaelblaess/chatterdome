"""Fremdtext mit eckigen Klammern darf die Oberflaeche nicht umbringen.

Am 12.08.2026 ist die App abgestuerzt, weil der letzte Prompt einer Sitzung
``[/usage-Screenshot]`` enthielt. rich las darin ein schliessendes Element ohne
oeffnendes und warf einen MarkupError - sichtbar wurde er erst beim Ziehen einer
Trennlinie, weil erst dann die Inhaltshoehe neu berechnet wurde.

Geprueft wird deshalb jeder Kanal, durch den Fremdtext in ein Ziel geht, das
Auszeichnungen auswertet. Fremdtext ist alles, was nicht aus den Sprachdateien
stammt: Prompts, Pfade, Bus-Nachrichten, Fehlerausgaben von Unterprozessen.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console
from rich.text import Text
from textual.coordinate import Coordinate
from textual_widgets import LogPanel

from claude_sanctuary.kern.gedaechtnis import Notiz
from claude_sanctuary.kern.modelle import Agent, Bestand, Busbestand, Namenspool
from claude_sanctuary.tui.app import SanctuaryApp
from claude_sanctuary.tui.schutz import klartext, klartext_oder_nichts
from claude_sanctuary.tui.screens.detail_screen import DetailScreen
from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenDaten, AgentenTabelle
from claude_sanctuary.tui.widgets.notizen_tabelle import NotizenDaten, NotizenTabelle

GIFT = "hier sind die aktuellen Stats: [/usage-Screenshot] sind die Rechnergebunden?"
"""Der Text, an dem die App tatsaechlich gestorben ist.

Bewusst der Originalsatz und kein konstruiertes ``[/x]``: so bleibt im Test
sichtbar, dass das ein voellig gewoehnlicher Satz ist und kein Sonderfall.
"""


def _gerendert(renderable: object) -> str:
    """Rendert wie das Terminal - hier faellt ein MarkupError auf, nicht frueher."""
    puffer = io.StringIO()
    Console(width=100, file=puffer, force_terminal=False).print(renderable)
    return puffer.getvalue()


def _agent(**abweichend: object) -> Agent:
    werte: dict[str, object] = {
        "name": "Snorre",
        "status": "arbeitet",
        "rechner": "TESTHOST",
        "pid": 4711,
        "session_id": "c53a2e7d-1d09",
        "laufzeit_ms": 60_000,
        "kontext": 120_000,
        "tokens": 5_000,
        "modell": "opus",
        "version": "2.0.1",
        "letztes_tool": "Bash",
        "letzte_zeit": "2026-08-12T10:00:00Z",
        "aufgabe": GIFT,
        "cwd": "C:/repos/x",
    }
    werte.update(abweichend)
    return Agent(**werte)  # type: ignore[arg-type]


class TestSchutz:
    def test_klartext_macht_aus_der_klammer_wieder_zeichen(self) -> None:
        assert "[/usage-Screenshot]" in Text.from_markup(klartext(GIFT)).plain

    def test_nichts_bleibt_nichts(self) -> None:
        # Ein Hinweisfeld erwartet None - ein leerer Text ergaebe ein leeres
        # Kaestchen am Mauszeiger.
        assert klartext_oder_nichts(None) is None


class TestDetailansicht:
    """Die Ansicht, an der der Absturz reproduzierbar war."""

    def test_prompt_mit_klammer_reisst_die_arbeitsansicht_nicht_um(self) -> None:
        block = DetailScreen(_agent())._block_arbeit()

        assert "usage-Screenshot" in _gerendert(block)

    @pytest.mark.parametrize(
        "feld",
        ["name", "rechner", "modell", "version", "letztes_tool", "system", "cwd", "aufgabe"],
    )
    def test_jedes_fremdfeld_haelt_stand(self, feld: str) -> None:
        """Nicht nur der Prompt: der Schutz sitzt am Kanal, also an allen Feldern.

        Der Ordnerpfad ist der naechste realistische Fall - Windows-Pfade mit
        eckigen Klammern gibt es, und der Pfad kommt ungeprueft vom Rechner.
        """
        schirm = DetailScreen(_agent(**{feld: GIFT}))

        for block in (schirm._block_sitzung(), schirm._block_rechner(), schirm._block_arbeit()):
            _gerendert(block)


class StilleQuelle:
    """Liefert einen Agenten mit vergiftetem Prompt, ohne Unterprozesse."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        return Bestand(rechner="TESTHOST", zeit="2026-08-12T10:00:00Z", agenten=[_agent()])

    def namen(self) -> Namenspool:
        return Namenspool()

    def verlauf(self, name: str) -> list[object]:
        return []

    def bestandsverlauf(self, grenze: int = 0) -> Busbestand:
        return Busbestand(rechner="TESTHOST", zeit="")


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> SanctuaryApp:
    gebaut = SanctuaryApp(quelle=StilleQuelle())
    monkeypatch.setattr(gebaut, "_frage_disclaimer", lambda: None)
    return gebaut


class TestHinweisfenster:
    """Ein Hinweisfenster ist ein Static und wertet Auszeichnungen aus."""

    async def test_der_hinweis_zeigt_den_prompt_woertlich(self, app: SanctuaryApp) -> None:
        async with app.run_test() as pilot:
            for _ in range(60):
                await pilot.pause()
                if app.query_one("#agenten-daten", AgentenDaten).row_count:
                    break
            tabelle = app.query_one("#agenten-daten", AgentenDaten)
            spalte = AgentenTabelle._AUFGABEN_SPALTE

            tabelle.watch_hover_coordinate(Coordinate(0, 0), Coordinate(0, spalte))

            assert tabelle.tooltip is not None
            # Der Hinweis muss das Zeichen zeigen, nicht daran ersticken.
            assert "[/usage-Screenshot]" in Text.from_markup(tabelle.tooltip).plain


class TestLog:
    """Das LogPanel schreibt mit markup=True - ungeschuetzt stirbt es hier."""

    async def test_fehlerausgabe_mit_klammer_landet_im_log(self, app: SanctuaryApp) -> None:
        async with app.run_test() as pilot:
            app._schreibe_log(f"Unterprozess meldete: {GIFT}", "error")
            await pilot.pause()

            geschrieben = "\n".join(app.query_one("#log", LogPanel)._lines)
            assert "usage-Screenshot" in geschrieben


class TestNotizhinweis:
    """Notizen kommen aus fremden Dateien, ihre Beschreibung ist Fremdtext."""

    async def test_beschreibung_mit_klammer_bleibt_lesbar(self, app: SanctuaryApp) -> None:
        notiz = Notiz(name="test", datei=Path("test.md"), beschreibung=GIFT)

        async with app.run_test() as pilot:
            app.query_one("#notizen", NotizenTabelle).uebernehmen([notiz])
            await pilot.pause()
            tabelle = app.query_one("#notizen-daten", NotizenDaten)

            tabelle.watch_hover_coordinate(
                Coordinate(0, 0), Coordinate(0, NotizenTabelle._BESCHREIBUNG)
            )

            assert tabelle.tooltip is not None
            assert "[/usage-Screenshot]" in Text.from_markup(tabelle.tooltip).plain
