"""Der Reiter "Diskussion": Formular, Chat und Verdrahtung mit der App.

Der eigentliche Ablauf (Fenster, Bus, claude -p) wird ersetzt - hier geht es
darum, was das Formular verlangt, was es zurueckgibt, und wie der Chat aussieht.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from test_app import FakeQuelle, _gefuellt  # pytest legt tests/ in den Suchpfad
from textual.widgets import Button, Checkbox, Input, Select, Static

from claude_sanctuary import debatte_ablauf
from claude_sanctuary.debatte_ablauf import Ergebnis
from claude_sanctuary.kern.debatte import Beitrag, Diskussion, Teilnehmer
from claude_sanctuary.tui.app import SanctuaryApp
from claude_sanctuary.tui.widgets.diskussion_panel import DiskussionsPanel, _AgentZeile


def _app() -> SanctuaryApp:
    # FakeQuelle aus test_app erfuellt das Protokoll nicht ganz (bestandsverlauf
    # fehlt) - dieselbe Altlast wie dort, fuer diese Tests ohne Belang.
    app = SanctuaryApp(quelle=FakeQuelle())  # type: ignore[arg-type]
    app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
    return app


async def _reiter(app: SanctuaryApp, pilot: Any) -> DiskussionsPanel:
    await _gefuellt(app, pilot)
    app.query_one("#bereiche").active = "tab-diskussion"  # type: ignore[attr-defined]
    panel = app.query_one("#diskussion", DiskussionsPanel)
    for _ in range(40):
        await pilot.pause()
        if list(panel.query(_AgentZeile)):
            return panel
    raise AssertionError("die Agentenliste im Reiter wurde nicht gefuellt")


def _text(panel: DiskussionsPanel, widget_id: str) -> str:
    return str(panel.query_one(widget_id, Static).render())


def _zeile(panel: DiskussionsPanel, name: str) -> _AgentZeile:
    return next(z for z in panel.query(_AgentZeile) if z.agent.name == name)


class TestFormular:
    async def test_eigene_sitzung_steht_nicht_zur_wahl(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            namen = [z.agent.name for z in panel.query(_AgentZeile)]
            assert "Klara" in namen
            assert "Lino" not in namen

    async def test_ohne_thema_gesperrt_mit_grund(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            assert panel.query_one("#disk-starten", Button).disabled
            assert "Es fehlt ein Thema." in _text(panel, "#disk-grund")

    async def test_seite_je_agent_und_benannte_positionen(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            panel.query_one("#disk-thema", Input).value = "Unity oder Godot?"
            panel.query_one("#disk-position-pro", Input).value = "Unity"
            panel.query_one("#disk-position-contra", Input).value = "Godot"
            zeile = _zeile(panel, "Klara")
            zeile.query_one(Checkbox).value = True
            zeile.query_one(Select).value = "contra"
            panel.query_one("#disk-neu", Input).value = "1"
            await pilot.pause()
            auftrag, grund = panel.auftrag()
            assert grund == ""
            assert auftrag is not None
            assert [(t.name, t.seite) for t in auftrag.diskussion.teilnehmer] == [
                ("Klara", "contra")]
            # Der frische bekommt die Gegenseite, obwohl er als zweiter kommt.
            assert [t.seite for t in auftrag.neu] == ["pro"]
            assert auftrag.diskussion.positionen == ("Unity", "Godot")
            assert "PRO (Unity): neu 1" in _text(panel, "#disk-vorschau")
            assert "CONTRA (Godot): Klara" in _text(panel, "#disk-vorschau")

    async def test_ein_teilnehmer_reicht_nicht(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            panel.query_one("#disk-thema", Input).value = "x"
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            await pilot.pause()
            assert panel.query_one("#disk-starten", Button).disabled
            assert "mindestens zwei" in _text(panel, "#disk-grund")
            assert panel.query_one("#disk-ohne-kontext", Checkbox).disabled

    async def test_haken_ueberleben_eine_aktualisierung(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            app.aktualisieren()
            for _ in range(40):
                await pilot.pause()
            assert _zeile(panel, "Klara").angekreuzt


def _beitrag(name: str, seite: str, text: str, **werte: Any) -> Beitrag:
    return Beitrag(1, name, text, "13:00:00", seite=seite, **werte)


class TestChat:
    async def test_pro_links_contra_rechts_und_keine_notizen_im_chat(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("Unity oder Godot?",
                           [Teilnehmer("Agatha", seite="pro"), Teilnehmer("Maria", seite="contra")],
                           positionen=("Unity", "Godot"), recherche=True)
            panel.beginnen(d, [])
            panel.beitrag(Beitrag(0, "Maria", "- geheime Notiz", "12:59:00",
                                  "vorbereitung", seite="contra"))
            panel.beitrag(_beitrag("Agatha", "pro", "Unity liefert schneller."))
            panel.beitrag(_beitrag("Maria", "contra", "Gestrichen ist das richtige Wort."))
            await pilot.pause()
            chat = panel.query_one("#disk-chat")
            blasen = list(chat.query(".disk-blase"))
            assert len(blasen) == 2
            links, rechts = blasen
            assert links.region.x < rechts.region.x, "PRO muss links stehen"
            assert "Agatha" in str(links.render()) and "Unity" in str(links.render())
            assert "Godot" in str(rechts.render())
            alles = " ".join(str(w.render()) for w in chat.children)
            assert "geheime Notiz" not in alles
            assert "Maria hat recherchiert." in alles

    async def test_gescheiterte_recherche_steht_an_der_blase(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            panel.beginnen(d, [])
            panel.beitrag(_beitrag("A", "pro", "Behauptung.", ungeprueft=True))
            await pilot.pause()
            blase = panel.query_one(".disk-blase")
            assert "nicht live geprüft" in str(blase.render())

    async def test_zusammenfassung_unter_dem_chat_nicht_darin(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            panel.beginnen(d, [])
            d.zusammenfassung = "Beide Seiten ..."
            panel.fertig(d, "1 Runde gespielt", "C:/protokoll.md")
            await pilot.pause()
            chat_text = " ".join(str(w.render()) for w in panel.query_one("#disk-chat").children)
            assert "Beide Seiten" not in chat_text
            assert "Beide Seiten" in _text(panel, "#disk-zusammenfassung")
            assert panel.query_one("#disk-neue", Button).display


class TestAblauf:
    async def test_starten_laeuft_im_hintergrund_und_gibt_frei(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aufrufe: list[tuple[Diskussion, list[Teilnehmer]]] = []

        def ablauf(diskussion: Diskussion, neu: list[Teilnehmer], **werte: Any) -> Ergebnis:
            aufrufe.append((diskussion, neu))
            werte["beim_beitrag"](_beitrag("Klara", "pro", "Mein Argument."))
            diskussion.ende = "1 Runde gespielt"
            return Ergebnis(diskussion)

        monkeypatch.setattr(debatte_ablauf, "ausfuehren", ablauf)
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            panel.query_one("#disk-thema", Input).value = "Thema"
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            panel.query_one("#disk-neu", Input).value = "1"
            await pilot.pause()
            await pilot.click("#disk-starten")
            await app.workers.wait_for_complete()
            for _ in range(20):
                await pilot.pause()
            assert len(aufrufe) == 1
            assert len(list(panel.query(".disk-blase"))) == 1
            assert panel.has_class("fertig")
            assert app._diskussion_stopp is None

    async def test_anhalten_setzt_das_signal(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            stopp = threading.Event()
            app._diskussion_stopp = stopp
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            panel.beginnen(d, [])
            await pilot.pause()
            await pilot.click("#disk-anhalten")
            await pilot.pause()
            assert stopp.is_set()


class TestPlatz:
    async def test_formular_passt_auf_100_mal_30(self) -> None:
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            panel = await _reiter(app, pilot)
            formular = panel.query_one("#disk-formular")
            for widget_id in ("#disk-thema", "#disk-position-pro", "#disk-runden"):
                bereich = panel.query_one(widget_id).region
                assert bereich.width > 1, widget_id
                assert formular.region.contains_region(bereich), widget_id
