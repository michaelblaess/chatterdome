"""Den Gedaechtnis-Tab headless fahren.

Geprueft wird die Verdrahtung, nicht die Analyse: kommen die Notizen in der
Tabelle an, zeigt die rechte Seite Uebersicht und Detail, greifen Filter und
Sortierung. Der Bestand wird dafuer in einem eigenen Verzeichnis aufgebaut -
das echte Gedaechtnis unter ~/.claude/memory waere von Michaels Arbeitsstand
abhaengig und morgen rot, ohne dass sich Code geaendert haette.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from claude_sanctuary.kern.gedaechtnis import Recallbericht, lade_gedaechtnis
from claude_sanctuary.kern.modelle import Bestand, Namenspool
from claude_sanctuary.tui import app as app_modul
from claude_sanctuary.tui.app import SanctuaryApp
from claude_sanctuary.tui.widgets.notizen_tabelle import NotizenTabelle, zustand


class StilleQuelle:
    """Keine Unterprozesse - hier geht es nur um den Gedaechtnis-Tab."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        return Bestand(rechner="TESTHOST", zeit="")

    def namen(self) -> Namenspool:
        return Namenspool()

    def verlauf(self, name: str, *, session_id: str = "", seit: str = "") -> list[object]:
        return []


def _notiz(ordner: Path, name: str, typ: str = "project", rumpf: str = "Text.") -> None:
    (ordner / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: Notiz {name}\nmetadata:\n"
        f"  node_type: memory\n  type: {typ}\n---\n\n{rumpf}\n",
        encoding="utf-8",
        newline="\n",
    )


@pytest.fixture
def gedaechtnis(tmp_path: Path) -> Path:
    """Ein kleiner, aber vollstaendiger Bestand mit allen Zustaenden."""
    ordner = tmp_path / "memory"
    ordner.mkdir()
    _notiz(ordner, "project_gross", rumpf="\n".join(["Zeile"] * 40))
    _notiz(ordner, "project_klein", rumpf="Siehe [[project_gross]].")
    _notiz(ordner, "reference_waise", typ="reference")
    (ordner / "MEMORY.md").write_text(
        "- [Gross](project_gross.md) - viel Text\n- [Klein](project_klein.md) - wenig\n",
        encoding="utf-8",
        newline="\n",
    )
    return ordner


@pytest.fixture
def app(gedaechtnis: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SanctuaryApp:
    (tmp_path / "settings.json").write_text(
        json.dumps({"gedaechtnis_pfad": str(gedaechtnis)}),
        encoding="utf-8",
        newline="\n",
    )
    # Ohne diese Ersatzfunktion liest der Test die ECHTEN Transkripte unter
    # ~/.claude/projects - hunderte Megabyte, abhaengig davon, wer den Test
    # gerade laufen laesst.
    monkeypatch.setattr(
        app_modul, "zaehle_recalls", lambda projekte, namen: Recallbericht(dateien=0)
    )
    gebaut = SanctuaryApp(quelle=StilleQuelle())
    monkeypatch.setattr(gebaut, "_frage_disclaimer", lambda: None)
    return gebaut


class TestTab:
    async def test_taste_m_oeffnet_den_tab_und_laedt(self, app: SanctuaryApp) -> None:
        async with app.run_test() as pilot:
            await pilot.press("m")
            for _ in range(200):
                await pilot.pause()
                if app._gedaechtnis is not None:
                    break

            assert app.query_one("#bereiche").active == "tab-gedaechtnis"
            assert app._gedaechtnis is not None
            assert app._gedaechtnis.anzahl == 3

    async def test_notizen_stehen_in_der_tabelle(self, app: SanctuaryApp) -> None:
        async with app.run_test() as pilot:
            await pilot.press("m")
            for _ in range(200):
                await pilot.pause()
                if app._gedaechtnis is not None:
                    break
            for _ in range(20):
                await pilot.pause()

            tabelle = app.query_one("#notizen-daten", DataTable)
            assert tabelle.row_count == 3

    async def test_uebersicht_nennt_beide_kosten(self, app: SanctuaryApp) -> None:
        async with app.run_test() as pilot:
            await pilot.press("m")
            for _ in range(200):
                await pilot.pause()
                if app._gedaechtnis is not None:
                    break
            for _ in range(20):
                await pilot.pause()

            text = str(app.query_one("#gedaechtnis-inhalt", Static).content)
            # Die Gegenueberstellung ist der Zweck des Tabs - fehlt sie, ist
            # das Panel eine blosse Dateiliste.
            assert "MEMORY.md" in text
            assert "Token" in text

    async def test_auswahl_zeigt_die_notiz_und_esc_fuehrt_zurueck(
        self, app: SanctuaryApp
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.press("m")
            for _ in range(200):
                await pilot.pause()
                if app._gedaechtnis is not None:
                    break
            for _ in range(20):
                await pilot.pause()

            # Wie der Anwender: in die Tabelle gehen und blaettern. Ein
            # move_cursor(row=0) waere wirkungslos, der Cursor steht dort schon.
            app.query_one("#notizen-daten", DataTable).focus()
            await pilot.pause()
            await pilot.press("down")
            for _ in range(20):
                await pilot.pause()

            assert app._notiz is not None
            text = str(app.query_one("#gedaechtnis-inhalt", Static).content)
            assert app._notiz.name in text

            # Ohne Rueckweg saesse der Anwender nach dem ersten Klick fest.
            await pilot.press("escape")
            for _ in range(20):
                await pilot.pause()
            assert app._notiz is None
            zurueck = str(app.query_one("#gedaechtnis-inhalt", Static).content)
            assert "MEMORY.md" in zurueck

    async def test_fehlendes_verzeichnis_meldet_den_pfad(
        self, app: SanctuaryApp, tmp_path: Path
    ) -> None:
        (tmp_path / "settings.json").write_text(
            json.dumps({"gedaechtnis_pfad": str(tmp_path / "gibt-es-nicht")}),
            encoding="utf-8",
            newline="\n",
        )
        async with app.run_test() as pilot:
            await pilot.press("m")
            for _ in range(200):
                await pilot.pause()
                if app._gedaechtnis is not None:
                    break
            for _ in range(20):
                await pilot.pause()

            text = str(app.query_one("#gedaechtnis-inhalt", Static).content)
            # Ohne diesen Zweig bliebe "wird gelesen" stehen und ein falscher
            # Pfad saehe aus wie ein haengendes Programm.
            assert "gibt-es-nicht" in text


class TestTabelle:
    async def test_filter_engt_ein_und_meldet_leere_treffer(
        self, app: SanctuaryApp
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.press("m")
            for _ in range(200):
                await pilot.pause()
                if app._gedaechtnis is not None:
                    break
            for _ in range(20):
                await pilot.pause()
            tabelle = app.query_one("#notizen", NotizenTabelle)

            tabelle.setze_filter("waise")
            for _ in range(10):
                await pilot.pause()
            assert app.query_one("#notizen-daten", DataTable).row_count == 1
            assert not app.query_one("#notizen-leer", Static).display

            tabelle.setze_filter("gibtesnicht")
            for _ in range(10):
                await pilot.pause()
            assert app.query_one("#notizen-daten", DataTable).row_count == 0
            assert app.query_one("#notizen-leer", Static).display, (
                "Eine leere Tabelle ohne Hinweis sieht aus wie ein Fehler"
            )

    async def test_sortierung_nach_zeilen_setzt_die_groesste_nach_oben(
        self, app: SanctuaryApp
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.press("m")
            for _ in range(200):
                await pilot.pause()
                if app._gedaechtnis is not None:
                    break
            for _ in range(20):
                await pilot.pause()

            tabelle = app.query_one("#notizen", NotizenTabelle)
            assert tabelle._sichtbar[0].name == "project_gross"


class TestZustand:
    def test_ampel_trennt_fehler_von_hinweis(self, gedaechtnis: Path) -> None:
        bestand = lade_gedaechtnis(gedaechtnis)
        nach_name = {n.name: zustand(n) for n in bestand.notizen}

        # Ohne Index-Eintrag ist eine Notiz fuer Claude unsichtbar - ein Fehler.
        assert nach_name["reference_waise"] == "fehler"
        # Auf project_klein verweist niemand. Das ist ein Hinweis, kein Fehler,
        # sonst waeren 45 von 164 Notizen faelschlich rot.
        assert nach_name["project_klein"] == "hinweis"
        assert nach_name["project_gross"] == "gut"
