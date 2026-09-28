"""Dialog und Ablauf der Diskussion in der Oberflaeche.

Der eigentliche Ablauf (Fenster oeffnen, Bus, claude -p) wird ersetzt - hier
geht es um die Verdrahtung: was der Dialog verlangt, was er zurueckgibt, und
dass die Taste eine laufende Diskussion anhaelt statt eine zweite zu starten.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from test_app import FakeQuelle, _gefuellt  # pytest legt tests/ in den Suchpfad
from textual.widgets import Button, Checkbox, Input, Static

from claude_sanctuary import debatte_ablauf
from claude_sanctuary.debatte_ablauf import Ergebnis
from claude_sanctuary.kern.debatte import Diskussion, Teilnehmer
from claude_sanctuary.tui.app import SanctuaryApp
from claude_sanctuary.tui.screens.bestaetigung_screen import BestaetigungScreen
from claude_sanctuary.tui.screens.diskussion_screen import DiskussionScreen


async def _dialog(app: SanctuaryApp, pilot: Any) -> DiskussionScreen:
    await _gefuellt(app, pilot)
    app.action_discussion()
    for _ in range(40):
        await pilot.pause()
        if isinstance(app.screen, DiskussionScreen):
            return app.screen
    raise AssertionError("der Dialog ging nicht auf")


def _app() -> SanctuaryApp:
    # FakeQuelle aus test_app erfuellt das Protokoll nicht ganz (bestandsverlauf
    # fehlt) - dieselbe Altlast wie dort, fuer diese Tests ohne Belang.
    app = SanctuaryApp(quelle=FakeQuelle())  # type: ignore[arg-type]
    app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
    return app


def _text(screen: DiskussionScreen, widget_id: str) -> str:
    return str(screen.query_one(widget_id, Static).render())


class TestDialog:
    async def test_ohne_thema_ist_starten_gesperrt_und_nennt_den_grund(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            screen = await _dialog(app, pilot)
            assert screen.query_one("#disk-starten", Button).disabled
            assert "Es fehlt ein Thema." in _text(screen, "#disk-grund")

    async def test_eigene_sitzung_steht_nicht_zur_wahl(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            screen = await _dialog(app, pilot)
            beschriftungen = [str(c.label) for c in screen.query(Checkbox)
                              if (c.id or "").startswith("disk-agent-")]
            assert any("Klara" in b for b in beschriftungen)
            assert not any("Lino" in b for b in beschriftungen)

    async def test_ein_teilnehmer_reicht_nicht(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            screen = await _dialog(app, pilot)
            screen.query_one("#disk-thema", Input).value = "Ist Angular tot?"
            screen.query_one("#disk-neu", Input).value = "0"
            screen.query_one("#disk-agent-0", Checkbox).value = True
            await pilot.pause()
            assert screen.query_one("#disk-starten", Button).disabled
            assert "mindestens zwei" in _text(screen, "#disk-grund")
            # Ohne frische Sitzungen gibt es keinen Kontext abzuschalten.
            assert screen.query_one("#disk-ohne-kontext", Checkbox).disabled

    async def test_vorschau_verteilt_pro_und_contra_wie_der_moderator(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            screen = await _dialog(app, pilot)
            screen.query_one("#disk-thema", Input).value = "Ist Angular tot?"
            screen.query_one("#disk-agent-0", Checkbox).value = True
            screen.query_one("#disk-neu", Input).value = "1"
            await pilot.pause()
            assert not screen.query_one("#disk-starten", Button).disabled
            vorschau = _text(screen, "#disk-vorschau")
            assert "PRO (Ja): Klara" in vorschau
            assert "CONTRA (Nein): neu 1" in vorschau

    async def test_unsinnige_runden_werden_benannt(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            screen = await _dialog(app, pilot)
            screen.query_one("#disk-thema", Input).value = "x"
            screen.query_one("#disk-runden", Input).value = "0"
            await pilot.pause()
            assert "Runden" in _text(screen, "#disk-grund")

    async def test_starten_gibt_den_auftrag_zurueck(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            screen = await _dialog(app, pilot)
            ergebnisse: list[Any] = []
            screen.dismiss = ergebnisse.append  # type: ignore[assignment,method-assign]
            screen.query_one("#disk-thema", Input).value = "Ist Angular tot?"
            screen.query_one("#disk-agent-0", Checkbox).value = True
            screen.query_one("#disk-neu", Input).value = "1"
            screen.query_one("#disk-recherche", Checkbox).value = True
            await pilot.pause()
            screen.action_starten()
            auftrag = ergebnisse[0]
            assert auftrag.diskussion.thema == "Ist Angular tot?"
            assert auftrag.diskussion.recherche is True
            assert [(t.name, t.seite) for t in auftrag.diskussion.teilnehmer] == [("Klara", "pro")]
            assert [t.seite for t in auftrag.neu] == ["contra"]
            assert auftrag.ohne_kontext is True


class TestPlatz:
    async def test_alles_sichtbar_auch_bei_100_mal_30(self) -> None:
        # Gemessen am 28.09.2026: vor dem Umbau auf einzeilige Felder lag der
        # Knopf "Starten" schon bei 120x40 unter der Kante.
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _dialog(app, pilot)
            for widget_id in ("#disk-thema", "#disk-format", "#disk-runden", "#disk-neu",
                              "#disk-recherche", "#disk-ohne-kontext", "#disk-starten"):
                bereich = screen.query_one(widget_id).region
                assert bereich.width > 1, widget_id
                assert bereich.y >= 0 and bereich.y + bereich.height <= 30, widget_id


class TestAblauf:
    async def test_lauf_schreibt_ins_log_und_gibt_die_taste_wieder_frei(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aufrufe: list[tuple[Diskussion, list[Teilnehmer]]] = []

        def ablauf(diskussion: Diskussion, neu: list[Teilnehmer], **werte: Any) -> Ergebnis:
            aufrufe.append((diskussion, neu))
            diskussion.ende = "1 Runde gespielt"
            return Ergebnis(diskussion)

        monkeypatch.setattr(debatte_ablauf, "ausfuehren", ablauf)
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            gemeldet: list[str] = []
            app._schreibe_log = lambda zeile, stufe="info": gemeldet.append(zeile)  # type: ignore[method-assign]
            from claude_sanctuary.tui.screens.diskussion_screen import DiskussionsAuftrag

            auftrag = DiskussionsAuftrag(
                diskussion=Diskussion("Thema", [Teilnehmer("Klara", seite="pro")]),
                neu=[Teilnehmer("neu 1", seite="contra")],
            )
            app._diskussion_bestaetigt(auftrag)
            assert app._diskussion_stopp is not None
            await app.workers.wait_for_complete()
            for _ in range(20):
                await pilot.pause()
            assert len(aufrufe) == 1
            assert any("Diskussion beendet" in z for z in gemeldet), gemeldet
            assert app._diskussion_stopp is None

    async def test_waehrend_der_diskussion_haelt_die_taste_an(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            stopp = threading.Event()
            app._diskussion_stopp = stopp
            app.action_discussion()
            for _ in range(20):
                await pilot.pause()
            assert isinstance(app.screen, BestaetigungScreen)
            assert not isinstance(app.screen, DiskussionScreen)
            app._diskussion_anhalten(True)
            assert stopp.is_set()
