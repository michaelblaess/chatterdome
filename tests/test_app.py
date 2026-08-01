"""Die Oberflaeche headless fahren.

Die Quelle wird ersetzt, damit der Test keinen laufenden Bus braucht - was
geprueft wird, ist die Verdrahtung: kommen die Daten in Tabelle, Kopf,
Statuszeile und Verlauf an, und reagieren die Tasten.
"""

from __future__ import annotations

import pytest
from textual.widgets import Button, DataTable, Input

from claude_sanctuary.kern.modelle import Agent, Auftrag, Bestand, Ereignis
from claude_sanctuary.tui.app import SanctuaryApp
from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenTabelle
from claude_sanctuary.tui.widgets.verlauf_panel import VerlaufPanel


class FakeQuelle:
    """Antwortet aus dem Gedaechtnis und merkt sich, was gesendet wurde."""

    def __init__(self) -> None:
        self.gesendet: list[tuple[str, str]] = []
        self.gestoppt: list[str] = []

    def bestand(self, *, mesh: bool = False) -> Bestand:
        return Bestand(
            rechner="TESTHOST",
            zeit="2026-08-01T19:00:00.000Z",
            agenten=[
                Agent(
                    name="Klara",
                    status="idle",
                    rechner="TESTHOST",
                    post=3,
                    kontext=700_000,
                    tokens=1000,
                    modell="claude-opus-5",
                    cwd="C:\\Repos\\test",
                ),
                # selbst=True: die Sitzung, die die Oberflaeche bedient.
                Agent(
                    name="Lino", status="busy", rechner="TESTHOST", tokens=500, selbst=True
                ),
            ],
        )

    def verlauf(self, name: str) -> list[Auftrag]:
        return [
            Auftrag(
                auftrag_id="a1",
                zustand="completed",
                von="Operator",
                an=name,
                text="Bitte pruefen",
                verlauf=[
                    Ereignis(art="auftrag", ts="", von="Operator", text="Bitte pruefen"),
                    Ereignis(art="quittung", ts="", von=name, status=200, notiz="erledigt"),
                ],
            )
        ]

    def senden(self, an: str, text: str, *, topic: str = "", quittung: bool = False) -> str:
        self.gesendet.append((an, text))
        return ""

    def stoppen(self, name: str) -> str:
        self.gestoppt.append(name)
        return ""


async def _gefuellt(app: SanctuaryApp, pilot: object) -> DataTable[object]:
    """Wartet, bis die erste Abfrage durch ist."""
    tabelle = app.query_one("#agenten-daten", DataTable)
    for _ in range(120):
        await pilot.pause()  # type: ignore[attr-defined]
        if tabelle.row_count:
            return tabelle
    raise AssertionError("Tabelle wurde nicht gefuellt")


@pytest.fixture
def quelle() -> FakeQuelle:
    return FakeQuelle()


class TestOberflaeche:
    async def test_agenten_erscheinen(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            assert tabelle.row_count == 2

    async def test_sortierung_schaltet_um(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            widget = app.query_one("#agenten", AgentenTabelle)
            spalten = list(tabelle.columns)
            vorher = [str(s.label) for s in tabelle.columns.values()]
            widget.on_data_table_header_selected(
                DataTable.HeaderSelected(tabelle, spalten[1], 1, "x")
            )
            await pilot.pause()
            nachher = [str(s.label) for s in tabelle.columns.values()]
            assert vorher != nachher
            assert "▲" in nachher[1]

    async def test_filter_reduziert(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            app.query_one("#agenten", AgentenTabelle).setze_filter("klara")
            await pilot.pause()
            assert tabelle.row_count == 1

    async def test_verlauf_erscheint_zur_auswahl(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            for _ in range(60):
                await pilot.pause()
            panel = app.query_one("#verlauf", VerlaufPanel)
            # Auftrag plus Quittung ergeben zwei Blasen.
            assert len(panel.children) == 2

    async def test_senden_ohne_text_meldet(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._senden()
            await pilot.pause()
            assert quelle.gesendet == []

    async def test_senden_legt_auftrag_ab(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app.query_one("#eingabe", Input).value = "Bitte Tests laufen lassen"
            app._senden()
            for _ in range(60):
                await pilot.pause()
                if quelle.gesendet:
                    break
            assert quelle.gesendet
            assert quelle.gesendet[0][1] == "Bitte Tests laufen lassen"
            assert app.query_one("#eingabe", Input).value == ""

    async def test_hilfe_oeffnet_und_schliesst(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            await pilot.press("h")
            await pilot.pause()
            assert type(app.screen).__name__ == "HilfeScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ != "HilfeScreen"

    async def test_eigene_sitzung_bekommt_keinen_auftrag(self, quelle: FakeQuelle) -> None:
        """An sich selbst wird nichts gesendet - Feld und Knopf sind gesperrt."""
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            # Nach Post absteigend steht Klara oben, die eigene Sitzung darunter.
            tabelle.move_cursor(row=1)
            await pilot.pause()
            assert app._gewaehlt is not None
            assert app._gewaehlt.selbst
            assert app.query_one("#senden", Button).disabled
            assert app.query_one("#eingabe", Input).disabled

            # Auch der Weg ueber die Eingabetaste fuehrt zu nichts.
            app.query_one("#eingabe", Input).value = "Hallo an mich"
            app._senden()
            for _ in range(20):
                await pilot.pause()
            assert quelle.gesendet == []

    async def test_fremder_agent_bleibt_sendbar(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            tabelle.move_cursor(row=0)
            await pilot.pause()
            assert not app.query_one("#senden", Button).disabled
