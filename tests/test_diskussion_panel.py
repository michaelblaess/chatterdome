"""Der Reiter "Diskussion": Formular, Chat und Verdrahtung mit der App.

Der eigentliche Ablauf (Fenster, Bus, claude -p) wird ersetzt - hier geht es
darum, was das Formular verlangt, was es zurueckgibt, und wie der Chat aussieht.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from test_app import FakeQuelle, _gefuellt  # pytest legt tests/ in den Suchpfad
from textual.widgets import Button, Checkbox, Input, Select, Static, TextArea

from chatterdome import debatte_ablauf
from chatterdome.debatte_ablauf import Ergebnis
from chatterdome.kern.debatte import Beitrag, Diskussion, Teilnehmer
from chatterdome.tui.app import ChatterdomeApp
from chatterdome.tui.widgets.diskussion_panel import DiskussionsPanel, _AgentZeile


def _app() -> ChatterdomeApp:
    # FakeQuelle aus test_app erfuellt das Protokoll nicht ganz (bestandsverlauf
    # fehlt) - dieselbe Altlast wie dort, fuer diese Tests ohne Belang.
    app = ChatterdomeApp(quelle=FakeQuelle())  # type: ignore[arg-type]
    app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
    return app


async def _reiter(app: ChatterdomeApp, pilot: Any) -> DiskussionsPanel:
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
            panel.query_one("#disk-thema", TextArea).text = "Unity oder Godot?"
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
            panel.query_one("#disk-thema", TextArea).text = "x"
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            await pilot.pause()
            assert panel.query_one("#disk-starten", Button).disabled
            assert "mindestens zwei" in _text(panel, "#disk-grund")
            # Bis zum 28.09.2026 war der Schalter ohne neue Agenten gesperrt, und
            # Michael konnte CLAUDE.md nicht einschalten. Er bleibt jetzt bedienbar.
            assert not panel.query_one("#disk-mit-kontext", Checkbox).disabled

    async def test_pruefen_gleich_nach_dem_einhaengen_neuer_zeilen(self) -> None:
        # Absturz vom 28.09.2026 bei Michael: NoMatches '.disk-agent-haken'. Die
        # Zeilen waren eingehaengt, ihre Kinder noch nicht aufgebaut, und die
        # Pruefung lief genau dazwischen.
        from chatterdome.kern.modelle import Agent

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            panel.query_one("#disk-thema", TextArea).text = "Thema"
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            await pilot.pause()
            panel.agenten_setzen([Agent(name="Klara", status="idle", rechner="TESTHOST"),
                                  Agent(name="Neu", status="idle", rechner="TESTHOST")])
            auftrag, grund = panel.auftrag()          # darf nicht werfen
            assert auftrag is None and "mindestens zwei" in grund
            for _ in range(20):
                await pilot.pause()
            # Und der Haken hat den Neuaufbau ueberlebt.
            assert _zeile(panel, "Klara").angekreuzt

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
            panel.query_one("#disk-thema", TextArea).text = "Thema"
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


class TestThemaMehrzeilig:
    async def test_drei_zeilen_und_umbrueche_werden_ein_satz(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            feld = panel.query_one("#disk-thema", TextArea)
            assert feld.region.height == 3
            feld.text = "Mad Max - Fury Road.\nAlte Fans mögen ihn nicht,\ndie jungen schon."
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            panel.query_one("#disk-neu", Input).value = "1"
            await pilot.pause()
            auftrag, _grund = panel.auftrag()
            assert auftrag is not None
            assert auftrag.diskussion.thema == (
                "Mad Max - Fury Road. Alte Fans mögen ihn nicht, die jungen schon.")


class TestVorgaben:
    async def test_research_ist_an(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            assert panel.query_one("#disk-recherche", Checkbox).value is True


class TestLesbarkeit:
    async def test_langer_beitrag_bekommt_einen_absatz(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            panel.beginnen(d, [])
            satz = "Das ist ein Satz mit genau zehn Woertern darin, wirklich wahr."
            panel.beitrag(_beitrag("A", "pro", " ".join([satz] * 6)))
            await pilot.pause()
            assert f"{satz}\n\n{satz}" in str(panel.query_one(".disk-blase").render())

    async def test_erwaehnte_agenten_in_der_farbe_ihrer_seite(self) -> None:
        from rich.text import Text

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("Agatha", seite="pro"),
                                 Teilnehmer("Maria", seite="contra")])
            panel.beginnen(d, [])
            text = Text("Maria, da irrst Du. Agatha bleibt dabei, Mariachi nicht.")
            panel._erwaehnungen(text, "Agatha")
            markiert = [(s.start, text.plain[s.start:s.end]) for s in text.spans]
            assert markiert == [(0, "Maria")], "nur andere, nur ganze Woerter"
            farbe = text.spans[0].style.color  # type: ignore[union-attr]
            assert farbe is not None
            assert farbe.name.lower() == app.theme_variables["accent"].lower()


def _gespeichert(app: ChatterdomeApp, *namen: str) -> Diskussion:
    d = Diskussion("Roundhouse oder Chinwag?",
                   [Teilnehmer(namen[0], seite="pro"), Teilnehmer(namen[1], seite="contra")],
                   runden=2, beginn="2026-09-28T17:12:00", ende="2 Runden gespielt")
    d.beitraege = [_beitrag(namen[0], "pro", "Erster."),
                   Beitrag(2, namen[1], "Zweiter.", "13:01:00", seite="contra")]
    app._archiv.speichern(d, "C:/ablage/20260928-171200.md")
    return d


class TestArchivImReiter:
    async def test_liste_zeigt_gespeicherte_und_oeffnet_den_chat(self) -> None:
        from textual.widgets import DataTable

        from chatterdome.tui.widgets.status_zeile import StatusZeile

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            _gespeichert(app, "Agatha", "Maria")
            panel = await _reiter(app, pilot)
            tabelle = panel.query_one("#disk-archiv", DataTable)
            assert tabelle.row_count == 1
            zeile = [str(z) for z in tabelle.get_row_at(0)]
            assert zeile[:3] == ["28.09.2026 17:12", "Agatha, Maria", "2"]
            tabelle.focus()
            await pilot.press("enter")
            for _ in range(10):
                await pilot.pause()
            assert panel.has_class("fertig")
            assert len(list(panel.query(".disk-blase"))) == 2
            assert panel.query_one("#disk-fortsetzen", Button).display
            status = str(app.query_one("#status", StatusZeile).render())
            assert "Runde: 2 / 2" in status and "20260928-171200.md" in status
            assert "C:/ablage/20260928-171200.md" in app._link_registry.values()
            # Zurueck zum Formular: die Bus-Kennzahlen kommen wieder.
            await pilot.click("#disk-neue")
            await pilot.pause()
            assert "Agenten:" in str(app.query_one("#status", StatusZeile).render())

    async def test_fortsetzen_startet_beendete_unter_ihrem_namen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aufrufe: list[dict[str, Any]] = []

        def ablauf(diskussion: Diskussion, neu: list[Teilnehmer], **werte: Any) -> Ergebnis:
            aufrufe.append({"diskussion": diskussion, **werte})
            diskussion.ende = "4 Runden gespielt"
            return Ergebnis(diskussion)

        monkeypatch.setattr(debatte_ablauf, "ausfuehren", ablauf)
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            d = _gespeichert(app, "Klara", "Ghost")      # Klara laeuft, Ghost nicht
            panel = await _reiter(app, pilot)
            app.post_message(DiskussionsPanel.Oeffnen(d.kennung))
            for _ in range(10):
                await pilot.pause()
            panel.query_one("#disk-weiter", Input).value = "2"
            panel.query_one("#disk-weiter-modell", Select).value = "haiku"
            panel.query_one("#disk-weiter-info", TextArea).text = "Parleyvoo ist frei."
            panel.query_one("#disk-weiter-kontext", Checkbox).value = True
            await pilot.pause()
            await pilot.click("#disk-fortsetzen")
            await app.workers.wait_for_complete()
            for _ in range(10):
                await pilot.pause()
            assert len(aufrufe) == 1
            weiter = aufrufe[0]
            assert weiter["diskussion"].runden == 4
            assert weiter["diskussion"].modell == "haiku"
            letzter = weiter["diskussion"].beitraege[-1]
            assert (letzter.art, letzter.text) == ("moderator", "Parleyvoo ist frei.")
            assert weiter["diskussion"].ohne_kontext is False
            # Der Hinweis steht als eigene Blase im Chat, nicht als Beitrag eines Agenten.
            assert "Parleyvoo ist frei." in str(panel.query_one(".disk-moderator").render())
            assert panel.query_one("#disk-weiter-info", TextArea).text == ""
            assert weiter["diskussion"].kennung == d.kennung
            assert [x.name for x in weiter["wiederbeleben"]] == ["Ghost"]
            assert str(weiter["protokoll"]).endswith("20260928-171200.md")

    async def test_archiv_neben_dem_formular_oder_darunter(self) -> None:
        for groesse, daneben in (((160, 50), True), ((120, 60), False)):
            app = _app()
            async with app.run_test(size=groesse) as pilot:
                panel = await _reiter(app, pilot)
                formular = panel.query_one("#disk-formular").region
                archiv = panel.query_one("#disk-archiv-raum").region
                assert archiv.height > 0, groesse
                if daneben:
                    assert archiv.x >= formular.right, groesse
                else:
                    assert archiv.y >= formular.bottom, groesse


class TestModellwahl:
    async def test_vorgabe_sonnet_und_im_auftrag(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            assert panel.query_one("#disk-modell", Select).value == "sonnet"
            panel.query_one("#disk-thema", TextArea).text = "Thema"
            panel.query_one("#disk-modell", Select).value = "opus"
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            panel.query_one("#disk-neu", Input).value = "1"
            await pilot.pause()
            auftrag, _grund = panel.auftrag()
            assert auftrag is not None and auftrag.diskussion.modell == "opus"

    async def test_fortsetzen_bietet_das_bisherige_modell_an(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro", modell="claude-haiku-4-5"),
                                 Teilnehmer("B", seite="contra")], modell="haiku", kennung=7)
            panel.zeigen(d, "")
            await pilot.pause()
            assert panel.query_one("#disk-weiter-modell", Select).value == "haiku"
            kopf = str(panel.query_one("#disk-kopf", Static).render())
            assert "Modell: Haiku (A: claude-haiku-4-5)" in kopf


class TestAnimationen:
    async def test_tipp_anzeige_auf_der_seite_des_redners_bis_zum_beitrag(self) -> None:
        from chatterdome.tui.widgets.diskussion_panel import _Laeuft

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            panel.beginnen(d, [])
            panel.redner("B", 1)
            await pilot.pause(0.3)
            tippt = panel.query_one(".disk-tippt", _Laeuft)
            assert tippt.has_class("disk-contra")
            erstes = tippt.zeile()
            assert "B schreibt" in erstes.plain
            await pilot.pause(0.5)
            assert tippt.zeile().spans != erstes.spans, "die Punkte laufen"
            panel.beitrag(_beitrag("B", "contra", "Nein."))
            await pilot.pause()
            assert not list(panel.query(_Laeuft))
            assert len(list(panel.query(".disk-blase"))) == 1

    async def test_recherche_je_teilnehmer_mit_fortschritt_im_kopf(self) -> None:
        from chatterdome.tui.widgets.diskussion_panel import _Laeuft

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            a, b = Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")
            panel.beginnen(Diskussion("x", [a, b], recherche=True), [])
            panel.vorbereitung_beginnt([a, b])
            await pilot.pause()
            assert [w.text for w in panel.query(_Laeuft)] == [
                "A recherchiert im Netz", "B recherchiert im Netz"]
            assert "0 von 2 fertig" in str(panel.query_one("#disk-kopf", Static).render())
            panel.beitrag(Beitrag(0, "A", "- Notiz", "13:00:00", "vorbereitung", seite="pro"))
            await pilot.pause()
            assert [w.text for w in panel.query(_Laeuft)] == ["B recherchiert im Netz"]
            meldung = str(panel.query(".disk-meldung").first().render())
            assert meldung.startswith("A hat recherchiert. (0:0")
            assert "1 von 2 fertig" in str(panel.query_one("#disk-kopf", Static).render())
            panel.fertig(panel._diskussion, "abgebrochen", "")  # type: ignore[arg-type]
            await pilot.pause()
            assert not list(panel.query(_Laeuft))

    def test_laufbalken_bleibt_im_rahmen(self) -> None:
        from chatterdome.tui.widgets.diskussion_panel import BALKEN_BREITE, _balken

        balken = [_balken(i) for i in range(60)]
        assert all(len(x) == BALKEN_BREITE and x.count("▰") == 5 for x in balken)
        assert len(set(balken)) > 10, "der Block bewegt sich"

    async def test_neue_diskussion_zeigt_nicht_das_alte_protokoll(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")],
                           kennung=3)
            panel.zeigen(d, "C:/alt.md")
            panel.beginnen(Diskussion("y", list(d.teilnehmer)), [])
            kennzahlen = panel.kennzahlen()
            assert kennzahlen is not None and kennzahlen[1] == ""


class TestHistorie:
    async def test_esc_fuehrt_zur_uebersicht(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            d = _gespeichert(app, "Agatha", "Maria")
            panel = await _reiter(app, pilot)
            panel.zeigen(d, "")
            panel.query_one("#disk-chat").focus()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not panel.has_class("fertig")
            assert panel.query_one("#disk-archiv").region.height > 0
            assert str(panel.query_one("#disk-neue", Button).label) == "Zur Übersicht"

    async def test_rechtsklick_oeffnet_das_kontextmenue(self) -> None:
        from textual_widgets import ContextMenuScreen

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            _gespeichert(app, "Agatha", "Maria")
            panel = await _reiter(app, pilot)
            # Erst wenn das Archiv neben dem Formular steht - die Klasse "breit"
            # setzt die Groessenmeldung nach dem Reiterwechsel, und ein Klick
            # davor trifft die alte Stelle.
            for _ in range(40):
                if panel.has_class("breit"):
                    break
                await pilot.pause()
            await pilot.pause()
            await pilot.click("#disk-archiv", offset=(4, 1), button=3)
            for _ in range(5):
                await pilot.pause()
            assert isinstance(app.screen, ContextMenuScreen)

    async def test_vorlage_fuellt_das_formular(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            d = _gespeichert(app, "Agatha", "Maria")
            panel = await _reiter(app, pilot)
            app._archiv_ziel = d.kennung
            app._archiv_menue_gewaehlt("vorlage")
            await pilot.pause()
            assert panel.query_one("#disk-thema", TextArea).text == d.thema
            assert panel.query_one("#disk-runden", Input).value == "2"

    async def test_loeschen_nur_nach_bestaetigung(self) -> None:
        from chatterdome.tui.screens.bestaetigung_screen import BestaetigungScreen

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            d = _gespeichert(app, "Agatha", "Maria")
            await _reiter(app, pilot)
            app._archiv_ziel = d.kennung
            app._archiv_menue_gewaehlt("loeschen")
            await pilot.pause()
            assert isinstance(app.screen, BestaetigungScreen)
            assert len(app._archiv.liste()) == 1, "noch nichts geloescht"
            app._archiv_loeschen_bestaetigt(True)
            assert app._archiv.liste() == []

    async def test_zur_uebersicht_steht_links_vom_fortsetzen(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            d = _gespeichert(app, "Agatha", "Maria")
            panel = await _reiter(app, pilot)
            panel.zeigen(d, "")
            await pilot.pause()
            links = panel.query_one("#disk-neue", Button).region
            rechts = panel.query_one("#disk-fortsetzen", Button).region
            assert links.width > 0 and links.right <= rechts.x


class TestPositionen:
    async def test_beschriftet_erklaert_und_im_team_ausgeblendet(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            zeile = panel.query_one("#disk-positionen")
            seiten = [str(w.render()) for w in zeile.query(".disk-seite")]
            assert seiten == ["PRO", "CONTRA"]
            assert "Entweder-oder" in str(panel.query_one("#disk-positionen-hinweis").render())
            hinweis = panel.query_one("#disk-positionen-hinweis")
            assert hinweis.region.height == 1, "passt in eine Zeile"
            panel.query_one("#disk-format", Select).value = "team"
            await pilot.pause()
            assert not zeile.display
            assert not panel.query_one("#disk-positionen-hinweis").display


class TestFarbenJePerson:
    async def test_team_abwechselnd_und_jeder_in_seiner_farbe(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("Agatha"), Teilnehmer("Maria")], format="team")
            panel.beginnen(d, [])
            panel.beitrag(_beitrag("Agatha", "", "Danke, Maria."))
            panel.beitrag(_beitrag("Maria", "", "Einig, Agatha."))
            await pilot.pause()
            agatha, maria = list(panel.query(".disk-blase"))
            # Im Team gibt es keine Seite - trotzdem eingerueckt, abwechselnd.
            assert agatha.region.x < maria.region.x
            links = agatha.styles.border_left[1]
            rechts = maria.styles.border_right[1]
            assert links != rechts, "jeder Sprecher hat seinen eigenen Balken"
            # Die Erwaehnung hat die Farbe des Erwaehnten, nicht das Grau von vorher.
            assert panel._farbe("Maria") == app.theme_variables["accent"]
            assert panel._farbe("Maria") != app.theme_variables.get("secondary")

    async def test_mehr_als_zwei_bekommen_verschiedene_farben(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            namen = ["A", "B", "C", "D"]
            panel.beginnen(Diskussion("x", [Teilnehmer(n) for n in namen], format="team"), [])
            assert len({panel._farbe(n) for n in namen}) == 4


class TestReinrufen:
    async def test_nachricht_geht_in_den_verlauf_und_die_tipp_anzeige_bleibt(self) -> None:
        from chatterdome.tui.widgets.diskussion_panel import _Laeuft

        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            app._laufende_diskussion = d
            panel.beginnen(d, [])
            panel.redner("B", 1)
            await pilot.pause()
            assert panel.query_one("#disk-zuruf-raum").display
            panel.query_one("#disk-zuruf", TextArea).text = "Bitte zum Schluss kommen."
            await pilot.click("#disk-reinrufen")
            await pilot.pause()
            assert [(b.art, b.text) for b in d.beitraege] == [
                ("moderator", "Bitte zum Schluss kommen.")]
            assert panel.query_one("#disk-zuruf", TextArea).text == ""
            kinder = list(panel.query_one("#disk-chat").children)
            moderator = panel.query_one(".disk-moderator")
            tippt = panel.query_one(".disk-tippt", _Laeuft)
            assert kinder.index(moderator) < kinder.index(tippt)

    async def test_nach_dem_ende_kein_reinrufen(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            await _reiter(app, pilot)
            app.post_message(DiskussionsPanel.Reinrufen("zu spaet"))
            await pilot.pause()
            assert app._laufende_diskussion is None

    async def test_statuszeile_sagt_spricht(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            panel.beginnen(d, [])
            panel.redner("A", 1)
            kennzahlen = panel.kennzahlen()
            assert kennzahlen is not None
            assert ("Spricht", "A") in [(p.label, p.value) for p in kennzahlen[0]]


def test_positionen_folgen_der_sprache_der_oberflaeche() -> None:
    """In der englischen Oberflaeche stand "PRO (Ja)" - gesehen im Demo-Screenshot 29.09.2026."""
    from chatterdome.i18n import load_locale
    from chatterdome.kern.debatte import CONTRA, PRO, Diskussion
    from chatterdome.tui.widgets.diskussion_panel import _position

    d = Diskussion("Tabs or spaces?", [])
    try:
        load_locale("en")
        assert (_position(d, PRO), _position(d, CONTRA)) == ("Yes", "No")
        # Die Anweisung an die Agenten bleibt deutsch.
        assert d.position(PRO) == "Ja"
        d.positionen = ("Unity", "Godot")
        assert _position(d, PRO) == "Unity"
    finally:
        load_locale("de")


class TestStimmungUndEntscheidung:
    async def test_formular_gibt_beides_weiter(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            panel.query_one("#disk-thema", TextArea).text = "Thema"
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            panel.query_one("#disk-neu", Input).value = "1"
            panel.query_one("#disk-stimmung", Select).value = "unfair"
            panel.query_one("#disk-entscheidung", Checkbox).value = True
            await pilot.pause()
            auftrag, grund = panel.auftrag()
            assert grund == ""
            assert auftrag is not None
            assert auftrag.diskussion.stimmung == "unfair"
            assert auftrag.diskussion.entscheidung is True

    async def test_im_team_gibt_es_keine_stimmung(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            panel.query_one("#disk-thema", TextArea).text = "Thema"
            _zeile(panel, "Klara").query_one(Checkbox).value = True
            panel.query_one("#disk-neu", Input).value = "1"
            panel.query_one("#disk-stimmung", Select).value = "aggressiv"
            panel.query_one("#disk-format", Select).value = "team"
            await pilot.pause()
            auftrag, _ = panel.auftrag()
            assert auftrag is not None
            assert auftrag.diskussion.stimmung == "sachlich"
            assert not panel.query_one("#disk-stimmung", Select).display

    async def test_die_stimme_steht_als_blase_mit_eigenem_kopf(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("x", [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")],
                           stimmung="fair", entscheidung=True)
            panel.beginnen(d, [])
            panel.beitrag(Beitrag(1, "A", "ENTSCHEIDUNG: Nein. Weil.", "10:00:00",
                                  "entscheidung", seite="pro"))
            await pilot.pause()
            blase = str(panel.query_one(".disk-blase", Static).render())
            assert "A · Abstimmung" in blase
            kopf = _text(panel, "#disk-kopf")
            assert "Stimmung: fair" in kopf
            assert "mit Abstimmung" in kopf


class TestZusammenfassungMenue:
    async def test_rechtsklick_oeffnet_das_menue_und_kopiert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from textual_widgets import ContextMenuScreen

        app = _app()
        kopiert: list[str] = []
        monkeypatch.setattr(app, "copy_to_clipboard", kopiert.append)
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            d = Diskussion("Ist Angular tot?",
                           [Teilnehmer("A", seite="pro"), Teilnehmer("B", seite="contra")])
            d.beitraege.append(_beitrag("A", "pro", "Mein Argument."))
            d.zusammenfassung = "Beide Seiten ..."
            panel.beginnen(d, [])
            panel.fertig(d, "1 Runde gespielt", "")
            await pilot.pause()
            await pilot.click("#disk-zusammenfassung", button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenuScreen)
            app.screen.dismiss(None)
            await pilot.pause()
            app._zusammenfassung_menue_gewaehlt("kopieren")
            app._zusammenfassung_menue_gewaehlt("alles_kopieren")
            assert kopiert[0] == "Beide Seiten ..."
            assert kopiert[1].startswith("# Ist Angular tot?")
            assert "## Zusammenfassung" in kopiert[1]


class TestFrageInHohemFenster:
    async def test_fuenf_zeilen_und_der_startknopf_bleibt_im_bild(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 70)) as pilot:
            panel = await _reiter(app, pilot)
            await pilot.pause()
            assert panel.has_class("hoch")
            assert panel.query_one("#disk-thema", TextArea).region.height == 5
            formular = panel.query_one("#disk-formular")
            knopf = panel.query_one("#disk-starten", Button)
            assert formular.region.contains_region(knopf.region)

    async def test_im_niedrigen_fenster_bleiben_es_drei(self) -> None:
        app = _app()
        async with app.run_test(size=(160, 50)) as pilot:
            panel = await _reiter(app, pilot)
            await pilot.pause()
            assert not panel.has_class("hoch")
            assert panel.query_one("#disk-thema", TextArea).region.height == 3
