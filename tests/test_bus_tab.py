"""Den Message-Bus-Tab headless fahren.

Geprueft wird die Verdrahtung, nicht die Auswahl-Logik - die steht in
test_busansicht.py. Der Bestand kommt aus einer Ersatzquelle: der echte Bus
unter ~/.claude/bus haengt davon ab, wer den Test gerade laufen laesst, und
waere morgen rot, ohne dass sich Code geaendert haette.
"""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, Select, Static

from chatterdome.kern.modelle import Auftrag, Bestand, Busbestand, Ereignis, Namenspool
from chatterdome.tui.app import ChatterdomeApp
from chatterdome.tui.widgets.bus_tabelle import BusTabelle


def _auftrag(
    kennung: str,
    *,
    zustand: str = "submitted",
    an: str = "Marga",
    text: str = "gib mir das aktuelle Datum",
    erstellt: str = "2026-08-07T09:19:51Z",
    an_session: str = "",
    bindung: str = "session",
    quittungen: list[Ereignis] | None = None,
) -> Auftrag:
    return Auftrag(
        auftrag_id=kennung,
        zustand=zustand,
        von="Chatterdome",
        an=an,
        topic="allgemein",
        text=text,
        erstellt=erstellt,
        an_session=an_session,
        bindung=bindung,
        verlauf=[Ereignis(art="auftrag", ts=erstellt, text=text), *(quittungen or [])],
    )


BESTAND = Busbestand(
    rechner="TESTHOST",
    zeit="2026-08-07T12:00:00Z",
    verfall_stunden=24,
    auftraege=[
        _auftrag("gebunden", an_session="4d0c0ab0-935e", bindung="session"),
        _auftrag("rolle", an="Schmid", text="Kudu-Skript ablegen", bindung="rolle"),
        _auftrag(
            "verfallen",
            zustand="expired",
            erstellt="2026-08-03T12:10:56Z",
            bindung="rolle",
            quittungen=[
                Ereignis(
                    art="quittung",
                    ts="2026-08-07T10:00:00Z",
                    von="bus",
                    zustand="expired",
                    status=408,
                    notiz="verfallen - lag laenger als 24 h offen",
                )
            ],
        ),
    ],
)


class StilleQuelle:
    """Keine Unterprozesse - hier geht es nur um den Bus-Tab."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        return Bestand(rechner="TESTHOST", zeit="")

    def namen(self) -> Namenspool:
        return Namenspool()

    def verlauf(self, name: str, *, session_id: str = "", seit: str = "") -> list[object]:
        return []

    def bestandsverlauf(self, grenze: int = 0) -> Busbestand:
        return BESTAND


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> ChatterdomeApp:
    gebaut = ChatterdomeApp(quelle=StilleQuelle())
    monkeypatch.setattr(gebaut, "_frage_disclaimer", lambda: None)
    return gebaut


async def _oeffnen(pilot: object, app: ChatterdomeApp) -> None:
    """Oeffnet den Tab und wartet, bis der Bestand steht."""
    await pilot.press("u")  # type: ignore[attr-defined]
    for _ in range(200):
        await pilot.pause()  # type: ignore[attr-defined]
        if app._busbestand is not None:
            break
    for _ in range(20):
        await pilot.pause()  # type: ignore[attr-defined]


class TestTab:
    async def test_taste_u_oeffnet_den_tab_und_laedt(self, app: ChatterdomeApp) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            assert app.query_one("#bereiche").active == "tab-bus"
            assert app._busbestand is not None
            assert len(app._busbestand.auftraege) == 3

    async def test_nachrichten_stehen_in_der_tabelle(self, app: ChatterdomeApp) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            assert app.query_one("#bus-daten", DataTable).row_count == 3

    async def test_uebersicht_nennt_offene_und_verfall(self, app: ChatterdomeApp) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            text = str(app.query_one("#bus-inhalt", Static).content)
            assert "24" in text, "die Frist gehoert in die Uebersicht"
            # Die Zahl der vererbbaren offenen Auftraege ist der Grund fuer den
            # Umbau vom 07.08.2026 - fehlt sie, ist die Uebersicht eine Liste.
            assert "1" in text

    async def test_zustandsfilter_engt_ein(self, app: ChatterdomeApp) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            app.query_one("#bus-zustand", Select).value = "gescheitert"
            for _ in range(20):
                await pilot.pause()

            assert app.query_one("#bus-daten", DataTable).row_count == 1

    async def test_bindungsfilter_trennt_person_von_rolle(self, app: ChatterdomeApp) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            app.query_one("#bus-bindung", Select).value = "person"
            for _ in range(20):
                await pilot.pause()

            assert app.query_one("#bus-daten", DataTable).row_count == 1

    async def test_suche_findet_ueber_den_agenten(self, app: ChatterdomeApp) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            app.query_one("#bus-liste", BusTabelle)._suche = "schmid"
            app.query_one("#bus-liste", BusTabelle)._neu_aufbauen()
            for _ in range(20):
                await pilot.pause()

            assert app.query_one("#bus-daten", DataTable).row_count == 1

    async def test_auswahl_zeigt_den_auftrag_und_esc_fuehrt_zurueck(
        self, app: ChatterdomeApp
    ) -> None:
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            tabelle = app.query_one("#bus-daten", DataTable)
            tabelle.focus()
            # move_cursor(row=0) loest kein Ereignis aus, wenn der Cursor schon
            # dort steht - deshalb eine echte Bewegung.
            await pilot.press("down")
            for _ in range(20):
                await pilot.pause()

            assert app._auftrag is not None
            text = str(app.query_one("#bus-inhalt", Static).content)
            assert "Chatterdome" in text

            await pilot.press("escape")
            for _ in range(20):
                await pilot.pause()

            assert app._auftrag is None

    async def test_verfallsgrund_steht_beim_auftrag(self, app: ChatterdomeApp) -> None:
        """Ohne den Grund fragt der Absender, wo sein Auftrag geblieben ist."""
        async with app.run_test() as pilot:
            await _oeffnen(pilot, app)

            app.query_one("#bus-liste", BusTabelle).post_message(
                BusTabelle.Ausgewaehlt(BESTAND.auftraege[2])
            )
            for _ in range(20):
                await pilot.pause()

            text = str(app.query_one("#bus-inhalt", Static).content)
            assert "408" in text
            assert "verfallen" in text
