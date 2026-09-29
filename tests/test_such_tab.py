"""Den Suchreiter headless fahren.

Geprueft wird die Verdrahtung, nicht der Index - der steht in test_suche.py.
Der Index landet ueber die autouse-Fixture in tmp_path, die Transkripte kommen
aus einem eigenen Verzeichnis: der echte Bestand unter ~/.claude/projects haengt
davon ab, wer den Test gerade startet.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import DataTable, Static, TabbedContent

from chatterdome.kern.modelle import Bestand, Busbestand, Namenspool
from chatterdome.kern.suche import Suchindex
from chatterdome.kern.transkripte import ClaudeQuelle
from chatterdome.tui.app import ChatterdomeApp
from chatterdome.tui.widgets.such_panel import SuchPanel


class StilleQuelle:
    """Keine Unterprozesse - hier geht es nur um den Suchreiter."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        return Bestand(rechner="TESTHOST", zeit="")

    def namen(self) -> Namenspool:
        return Namenspool()

    def verlauf(self, name: str, *, session_id: str = "", seit: str = "") -> list[object]:
        return []

    def bestandsverlauf(self, grenze: int = 0) -> Busbestand:
        return Busbestand(rechner="TESTHOST", verfall_stunden=24, auftraege=[])


@pytest.fixture
def projekte(tmp_path: Path) -> Path:
    wurzel = tmp_path / "projects"
    (wurzel / "repo").mkdir(parents=True)
    zeilen = [
        {
            "type": rolle,
            "timestamp": "2026-08-24T10:00:00Z",
            "sessionId": "s1",
            "message": {"content": [{"type": "text", "text": text}]},
        }
        for rolle, text in (
            ("user", "Wo lag noch mal der Fehler mit dem Glob"),
            ("assistant", "Eine Ebene zu flach - die Subagenten fielen heraus"),
        )
    ]
    (wurzel / "repo" / "s1.jsonl").write_text(
        "\n".join(json.dumps(z) for z in zeilen) + "\n", encoding="utf-8", newline="\n"
    )
    return wurzel


@pytest.fixture
def app(projekte: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ChatterdomeApp:
    gebaut = ChatterdomeApp(quelle=StilleQuelle())
    monkeypatch.setattr(gebaut, "_frage_disclaimer", lambda: None)
    # Der Index bekommt eine eigene Datei UND eine eigene Quelle - sonst liest
    # der Test den echten Bestand des Entwicklers.
    gebaut._suchindex = Suchindex(tmp_path / "suche.db")
    echt = gebaut._suchindex.aktualisiere
    monkeypatch.setattr(
        gebaut._suchindex,
        "aktualisiere",
        lambda quellen=None, melde=None: echt([ClaudeQuelle(projekte)], melde),
    )
    return gebaut


async def _oeffnen(pilot: Any, app: ChatterdomeApp) -> None:
    await pilot.press("f")
    for _ in range(300):
        await pilot.pause()
        if app._index_gebaut:
            break
    for _ in range(10):
        await pilot.pause()


async def _tippen(pilot: Any, app: ChatterdomeApp, text: str) -> None:
    """Tippt und wartet, bis die Entprellung die Abfrage ausgeloest hat.

    ``pilot.pause()`` gibt nur den Ereignisstrang frei und laesst KEINE Zeit
    vergehen - eine Schleife darueber wartet also nicht auf den Zeitgeber,
    sondern dreht sich in Mikrosekunden leer. Gewartet wird deshalb auf den
    ZUSTAND, mit echter Zeit dazwischen und einer Reissleine, damit ein Haenger
    die Suite nicht anhaelt.

    Der Zustand ist die AENDERUNG der Fusszeile, nicht ein bestimmter Text:
    was dort vorher stand, haengt davon ab, ob der Index gerade gebaut wurde.
    """
    fuss = app.query_one("#such-fuss", Static)
    vorher = str(fuss.content)
    for zeichen in text:
        await pilot.press(zeichen)
    grenze = time.monotonic() + 5.0
    while str(fuss.content) == vorher:
        if time.monotonic() > grenze:
            raise AssertionError("die Suche hat nach 5 s nicht geantwortet")
        await pilot.pause(0.05)


class TestSuchreiter:
    async def test_taste_oeffnet_und_baut_den_index(self, app: ChatterdomeApp) -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await _oeffnen(pilot, app)

            assert app.query_one("#bereiche").active == "tab-suche"
            assert app._index_gebaut is True
            assert app._suchindex.bestand() == (1, 2)

    async def test_cursor_steht_im_suchfeld(self, app: ChatterdomeApp) -> None:
        """Wer den Reiter oeffnet, will tippen - nicht erst ein Feld suchen."""
        async with app.run_test(size=(140, 45)) as pilot:
            await _oeffnen(pilot, app)

            fokus = app.focused
            assert fokus is not None and fokus.id == "such-eingabe"

    async def test_ctrl_f_oeffnet_die_suche_auch_aus_dem_filterfeld(
        self, app: ChatterdomeApp
    ) -> None:
        """Ctrl+F statt F10 (Michael am 29.09.2026) - auch mitten im Tippen.

        Aus dem Filterfeld heraus zaehlt es: ein Buchstabe ginge dort ins Feld,
        ctrl+f belegt Input nicht und kommt deshalb bei der App an.
        """
        async with app.run_test(size=(140, 45)) as pilot:
            app.action_focus_filter()
            await pilot.pause()
            assert app.focused is not None and app.focused.id == "agenten-filter"

            await pilot.press("ctrl+f")
            for _ in range(300):
                await pilot.pause()
                if app._index_gebaut:
                    break

            assert app.query_one("#bereiche", TabbedContent).active == "tab-suche"
            fokus = app.focused
            assert fokus is not None and fokus.id == "such-eingabe"

    async def test_index_wird_nur_einmal_gebaut(self, app: ChatterdomeApp) -> None:
        """EIN Tastendruck loest zwei Wege aus - gebaut werden darf nur einmal.

        ``action_show_search`` setzt den Reiter, das feuert ``TabActivated``,
        und beide Wege wollten den Aufbau starten. Zwei Thread-Worker laufen
        dann nebeneinander zu Ende (abbrechen laesst sich ein Thread nicht),
        treffen sich in der Datei, und SQLite meldet "database is locked".
        Sichtbar war das nur daran, dass der Fokus im Fehlerdialog des
        CrashGuard landete statt im Suchfeld.

        Gemessen ohne den Riegel: 2 Laeufe. Mit: 1.
        """
        laeufe: list[int] = []
        echt = app._suchindex.aktualisiere
        app._suchindex.aktualisiere = lambda quellen=None, melde=None: (
            laeufe.append(1) or echt(quellen, melde)
        )
        async with app.run_test(size=(140, 45)) as pilot:
            await _oeffnen(pilot, app)

        assert len(laeufe) == 1

    async def test_tippen_fuellt_die_trefferliste(self, app: ChatterdomeApp) -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await _oeffnen(pilot, app)
            await _tippen(pilot, app, "subagenten")

            tabelle = app.query_one("#such-treffer", DataTable)
            assert tabelle.row_count == 1

    async def test_ohne_treffer_bleibt_die_liste_leer(self, app: ChatterdomeApp) -> None:
        async with app.run_test(size=(140, 45)) as pilot:
            await _oeffnen(pilot, app)
            await _tippen(pilot, app, "nashorn")

            assert app.query_one("#such-treffer", DataTable).row_count == 0
            fuss = app.query_one("#such-fuss", Static)
            assert "Nichts gefunden" in str(fuss.content)

    async def test_syntaxzeichen_reissen_nichts_um(self, app: ChatterdomeApp) -> None:
        """Ein Anfuehrungszeichen in der Eingabe wuerde eine rohe Abfrage abbrechen."""
        async with app.run_test(size=(140, 45)) as pilot:
            await _oeffnen(pilot, app)
            await _tippen(pilot, app, 'glob"')

            # Zusicherung ist, dass die Oberflaeche noch steht.
            assert app.query_one("#suche", SuchPanel) is not None

    async def test_alle_bedienelemente_sind_sichtbar(self, app: ChatterdomeApp) -> None:
        """Ein Feld hinter dem unteren Rand ist vorhanden und trotzdem unbenutzbar."""
        async with app.run_test(size=(140, 30)) as pilot:
            await _oeffnen(pilot, app)

            schirm = app.screen.size.height
            for kennung in ("#such-zeile", "#such-treffer", "#such-fuss"):
                bereich = app.query_one(kennung).region
                assert bereich.y >= 0, kennung
                assert bereich.y + bereich.height <= schirm, kennung
                assert bereich.width > 1, kennung
