"""Die Oberflaeche headless fahren.

Die Quelle wird ersetzt, damit der Test keinen laufenden Bus braucht - was
geprueft wird, ist die Verdrahtung: kommen die Daten in Tabelle, Kopf,
Statuszeile und Verlauf an, und reagieren die Tasten.
"""

from __future__ import annotations

import pytest
from textual.widgets import Button, DataTable, Input

from claude_sanctuary.kern.modelle import Agent, Auftrag, Bestand, Ereignis, Namenspool
from claude_sanctuary.tui.app import ABSENDER, SanctuaryApp
from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenTabelle
from claude_sanctuary.tui.widgets.verlauf_panel import VerlaufPanel


class FakeQuelle:
    """Antwortet aus dem Gedaechtnis und merkt sich, was gesendet wurde."""

    def __init__(self) -> None:
        self.gesendet: list[tuple[str, str, str, str]] = []
        self.gestoppt: list[str] = []
        self.mit_tokens: list[bool] = []
        """Je Abfrage, ob der Verbrauch mit angefordert wurde."""

        self.fotos: list[str] = []
        self.foto_pfad = ""
        self.foto_fehler = "kein Desktop"

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        self.mit_tokens.append(tokens)
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

    def namen(self) -> Namenspool:
        return Namenspool(motiv="Comicmotiv", namen=["Lino", "Luzie"], frei=["Luzie"])

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

    def senden(
        self,
        an: str,
        text: str,
        *,
        topic: str = "",
        quittung: bool = False,
        host: str = "",
        von: str = "",
    ) -> str:
        self.gesendet.append((an, text, host, von))
        return ""

    def stoppen(self, name: str) -> str:
        self.gestoppt.append(name)
        return ""

    def bildschirmfoto(self, rechner: str = "") -> tuple[str, str]:
        self.fotos.append(rechner)
        return self.foto_pfad, self.foto_fehler


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
            _an, text, host, von = quelle.gesendet[0]
            assert text == "Bitte Tests laufen lassen"
            assert app.query_one("#eingabe", Input).value == ""
            # Der Rechner des Empfaengers MUSS mitgehen, sonst landet der
            # Auftrag auf dem Absenderrechner und der Empfaenger sieht ihn nie.
            assert host == "TESTHOST", "Zielrechner fehlt im Auftrag"
            # Ohne Absender stand in jedem Auftrag "unbekannt".
            assert von == ABSENDER

    async def test_verbrauch_nur_auf_zuruf(self, quelle: FakeQuelle) -> None:
        """Die Taktabfrage darf den Verbrauch NICHT mitholen.

        Der Operator liest dafuer jedes Transkript vollstaendig. Liefe das im
        Fuenf-Sekunden-Takt mit, waere die Oberflaeche dauerhaft langsam.
        """
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            assert quelle.mit_tokens, "keine Abfrage gelaufen"
            assert not any(quelle.mit_tokens), "Taktabfrage holt den Verbrauch mit"

            await pilot.press("v")
            for _ in range(60):
                await pilot.pause()
                if any(quelle.mit_tokens):
                    break
            assert any(quelle.mit_tokens), "v hat den Verbrauch nicht angefordert"

    async def test_eigener_rechner_ohne_ziel_aufgenommen(self, quelle: FakeQuelle) -> None:
        """Fuer den eigenen Rechner darf KEIN Ziel mitgehen.

        Mit Ziel ginge der Aufruf ueber ssh auf den eigenen Rechner - also
        durch den Dienstkontext, der unter Windows keinen Desktop sieht.
        """
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._bild_holen("TESTHOST")  # derselbe Rechner wie im Bestand
            for _ in range(60):
                await pilot.pause()
                if quelle.fotos:
                    break
            assert quelle.fotos == [""], f"Ziel wurde mitgegeben: {quelle.fotos}"

    async def test_fremder_rechner_wird_benannt(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._bild_holen("SENZA")
            for _ in range(60):
                await pilot.pause()
                if quelle.fotos:
                    break
            assert quelle.fotos == ["SENZA"]

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
            for _ in range(20):
                await pilot.pause()
                if app._gewaehlt is not None and app._gewaehlt.selbst:
                    break
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
            for _ in range(20):
                await pilot.pause()
                if app._gewaehlt is not None and not app._gewaehlt.selbst:
                    break
            assert not app.query_one("#senden", Button).disabled


class TestBedienung:
    """Doppelklick, Kontextmenue und Schnellbefehle."""

    async def test_doppelklick_oeffnet_die_detailansicht(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            tabelle.post_message(tabelle.DoppelKlick(tabelle, 0))
            for _ in range(30):
                await pilot.pause()
                if type(app.screen).__name__ == "DetailScreen":
                    break
            assert type(app.screen).__name__ == "DetailScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ != "DetailScreen"

    async def test_rechtsklick_oeffnet_das_kontextmenue(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            tabelle.post_message(tabelle.RechtsKlick(tabelle, 0, (10, 10)))
            for _ in range(30):
                await pilot.pause()
                if type(app.screen).__name__ == "ContextMenuScreen":
                    break
            assert type(app.screen).__name__ == "ContextMenuScreen"

    async def test_schnellbefehl_fuellt_nur_das_feld(self, quelle: FakeQuelle) -> None:
        """Der Text landet im Eingabefeld - gesendet wird bewusst separat."""
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._schnellbefehl("compact")
            await pilot.pause()
            assert "compact" in app.query_one("#eingabe", Input).value
            assert quelle.gesendet == []

    async def test_statusleiste_zeigt_kennzahlen(self, quelle: FakeQuelle) -> None:
        from textual_widgets import StatusBar

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            leiste = app.query_one("#status", StatusBar)
            text = leiste._build().plain
            assert "|" in text          # Trenner
            assert "2" in text          # zwei Agenten
            assert "Kontext" in text    # Verbrauch waere ohne --tokens immer 0
            assert leiste.styles.border.top[0] == "solid"

    async def test_namenspool_erscheint_im_kopf(self, quelle: FakeQuelle) -> None:
        from claude_sanctuary.tui.widgets.kopf_panel import KopfPanel

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            for _ in range(40):
                await pilot.pause()
            kopf = app.query_one("#kopf", KopfPanel)
            # _items ist ein dict key -> InfoItem (info_header.py:279).
            werte = {k: i.value for k, i in kopf._items.items()}
            assert werte["pool"] == "Comicmotiv"
            assert werte["free"] == "1"
