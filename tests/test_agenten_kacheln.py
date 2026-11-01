"""Tests der Kachelansicht: Zeichnung, Effekte und Bedienung.

Die Kacheln fuehren keine eigene Auswahl. Deshalb pruefen die Bedienungstests
immer gegen den Cursor der Tabelle und das, was die Anwendung gemeldet bekommt.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.cells import cell_len
from test_app import FakeQuelle  # pytest legt tests/ in den Suchpfad
from test_app import _gefuellt as _app_gefuellt
from textual.app import App, ComposeResult
from textual.widgets import DataTable, TabbedContent

from chatterdome.kern.einstellungen import Einstellungen
from chatterdome.kern.modelle import KONTEXT_KRITISCH, Agent
from chatterdome.tui.app import ChatterdomeApp
from chatterdome.tui.widgets import roboter
from chatterdome.tui.widgets.agenten_kacheln import (
    KACHEL_MINDESTBREITE,
    AgentenKachel,
    AgentenKacheln,
    Bild,
    bild_zu,
    kachel_text,
    spalten_fuer,
)
from chatterdome.tui.widgets.agenten_tabelle import (
    ANSICHT_KACHELN,
    ANSICHT_TABELLE,
    AgentenTabelle,
)
from chatterdome.tui.widgets.roboter import Gesicht


def _agent(name: str = "Agatha", **werte: object) -> Agent:
    return Agent(name=name, status=str(werte.pop("status", "idle")), rechner="PC",
                 session_id=f"sitzung-{name}", **werte)  # type: ignore[arg-type]


def _vor_tagen(tage: int) -> str:
    return (datetime.now().astimezone() - timedelta(days=tage)).isoformat()


class _Probe(App[None]):
    """Nur das Widget, damit die App nicht dazwischen aufraeumt."""

    def __init__(self, ansicht: str = ANSICHT_KACHELN) -> None:
        super().__init__()
        self._ansicht = ansicht
        self.ausgewaehlt: list[str | None] = []
        self.aufgerufen: list[str] = []
        self.menue: list[str] = []

    def compose(self) -> ComposeResult:
        yield AgentenTabelle(ansicht=self._ansicht, id="agenten")

    def on_agenten_tabelle_ausgewaehlt(self, ereignis: AgentenTabelle.Ausgewaehlt) -> None:
        self.ausgewaehlt.append(ereignis.agent.name if ereignis.agent else None)

    def on_agenten_tabelle_aufgerufen(self, ereignis: AgentenTabelle.Aufgerufen) -> None:
        self.aufgerufen.append(ereignis.agent.name)

    def on_agenten_tabelle_menue_gewuenscht(
        self, ereignis: AgentenTabelle.MenueGewuenscht
    ) -> None:
        self.menue.append(ereignis.agent.name)


NAMEN = ("Anna", "Bert", "Clara", "Dora", "Emil", "Frida", "Gustav")


async def _gefuellt(app: _Probe, pilot: object, namen: tuple[str, ...] = NAMEN) -> AgentenKacheln:
    tabelle = app.query_one("#agenten", AgentenTabelle)
    tabelle.uebernehmen([_agent(n) for n in namen])
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]
    return app.query_one("#agenten-kacheln", AgentenKacheln)


def _markiert(kacheln: AgentenKacheln) -> list[str]:
    return [k.agent.name for k in kacheln.query(AgentenKachel) if k.has_class("markiert")]


class TestRoboter:
    def test_jeder_name_sieht_immer_gleich_aus(self) -> None:
        erste = roboter.zeichne("Agatha", Gesicht.WACH, "#2ecc71")
        zweite = roboter.zeichne("agatha", Gesicht.WACH, "#2ecc71")
        assert [z.spans for z in erste] == [z.spans for z in zweite]

    def test_namen_bekommen_verschiedene_farben(self) -> None:
        farben = {roboter.gehaeusefarbe(n) for n in NAMEN}
        assert len(farben) > 1

    def test_jede_zeile_ist_gleich_breit(self) -> None:
        for name in NAMEN:
            for gesicht in Gesicht:
                zeilen = roboter.zeichne(name, gesicht, "#2ecc71", blick=1)
                assert len(zeilen) == roboter.HOEHE // 2
                assert {cell_len(z.plain) for z in zeilen} == {roboter.BREITE}

    def test_jedes_gesicht_sieht_anders_aus(self) -> None:
        bilder = {
            tuple(str(s) for z in roboter.zeichne("Agatha", g, "#2ecc71") for s in z.spans)
            for g in Gesicht
        }
        assert len(bilder) == len(Gesicht)

    def test_abdunkeln_rechnet_je_farbanteil(self) -> None:
        assert roboter.abdunkeln("#804020", 0.5) == "#402010"


class TestEffekte:
    def test_beschaeftigt_schaut_sich_um(self) -> None:
        agent = _agent(status="busy")
        blicke = {bild_zu(agent, False, takt).blick for takt in range(16)}
        assert blicke == {-1, 0, 1}
        assert bild_zu(agent, False, 0).gesicht is Gesicht.ARBEITET

    def test_frei_blinzelt_nur_selten(self) -> None:
        agent = _agent()
        gesichter = [bild_zu(agent, False, takt).gesicht for takt in range(32)]
        assert gesichter.count(Gesicht.BLINZELT) == 1
        assert gesichter.count(Gesicht.WACH) == 31

    def test_verwaist_schlaeft_auch_wenn_status_busy(self) -> None:
        assert bild_zu(_agent(status="busy"), True, 0).gesicht is Gesicht.SCHLAEFT

    def test_nicht_erreichbar_geht_vor(self) -> None:
        agent = _agent(erreichbar=False)
        assert bild_zu(agent, True, 0).gesicht is Gesicht.AUS

    def test_kritischer_kontext_blinkt(self) -> None:
        kritisch = _agent(kontext=KONTEXT_KRITISCH)
        assert {bild_zu(kritisch, False, t).warnung_an for t in range(8)} == {True, False}
        # Gegenprobe: unter der Schwelle blinkt nichts.
        assert {bild_zu(_agent(kontext=100), False, t).warnung_an for t in range(8)} == {False}

    def test_post_blinkt_nur_bis_zur_frist(self) -> None:
        agent = _agent(post=2)
        assert bild_zu(agent, False, 2, post_bis=4).post_an
        assert not bild_zu(agent, False, 4, post_bis=4).post_an


class TestInhalt:
    def test_alle_zeilen_passen_in_die_kleinste_kachel(self) -> None:
        breite = KACHEL_MINDESTBREITE - 2
        agent = _agent(
            name="Maximiliane-Friederike@SEHR-LANGER-RECHNER",
            aufgabe="Ein sehr langer Auftrag, der nie im Leben in eine Zeile passen wird",
            kontext=650_000,
            post=12,
            laufzeit_ms=500 * 3_600_000,
            fortgesetzt=True,
            letzte_zeit=_vor_tagen(120),
        )
        text = kachel_text(agent, agent.name, breite, Bild(Gesicht.SCHLAEFT), True)
        zeilen = text.plain.split("\n")
        assert len(zeilen) == 9
        assert max(cell_len(z) for z in zeilen) <= breite

    def test_fremdtext_bleibt_klartext(self) -> None:
        agent = _agent(aufgabe="[bold]kein Markup[/bold]")
        text = kachel_text(agent, agent.name, 40, Bild(Gesicht.WACH), False)
        assert "[bold]kein Markup[/bold]" in text.plain

    def test_verwaist_warnt_am_alter(self) -> None:
        agent = _agent(letzte_zeit=_vor_tagen(2))
        assert "⚠" in kachel_text(agent, agent.name, 30, Bild(Gesicht.SCHLAEFT), True).plain
        # Gegenprobe: ohne Befund keine Warnung.
        assert "⚠" not in kachel_text(agent, agent.name, 30, Bild(Gesicht.WACH), False).plain

    def test_post_steht_nur_da_wenn_welche_da_ist(self) -> None:
        mit = _agent(post=3)
        assert "✉ 3" in kachel_text(mit, mit.name, 30, Bild(Gesicht.WACH), False).plain
        ohne = _agent()
        assert "✉" not in kachel_text(ohne, ohne.name, 30, Bild(Gesicht.WACH), False).plain

    def test_spalten_folgen_der_breite(self) -> None:
        assert spalten_fuer(0) == 1
        assert spalten_fuer(40) == 1
        assert spalten_fuer(70) == 3
        assert spalten_fuer(92) == 4
        assert spalten_fuer(400) == 4


class TestBedienung:
    async def test_tabelle_ist_die_vorgabe(self) -> None:
        app = _Probe(ansicht="quatsch")
        async with app.run_test():
            tabelle = app.query_one("#agenten", AgentenTabelle)
            assert tabelle.ansicht == ANSICHT_TABELLE
            assert app.query_one("#agenten-daten", DataTable).display
            assert not app.query_one("#agenten-kacheln", AgentenKacheln).display

    async def test_umschalten_tauscht_die_ansicht_und_den_fokus(self) -> None:
        app = _Probe(ansicht=ANSICHT_TABELLE)
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            daten = app.query_one("#agenten-daten", DataTable)
            daten.focus()
            await pilot.pause()
            tabelle = app.query_one("#agenten", AgentenTabelle)

            assert tabelle.ansicht_wechseln() == ANSICHT_KACHELN
            await pilot.pause()
            assert kacheln.display and not daten.display
            assert app.focused is kacheln

            assert tabelle.ansicht_wechseln() == ANSICHT_TABELLE
            await pilot.pause()
            assert daten.display and not kacheln.display
            assert app.focused is daten

    async def test_umschalten_nimmt_einem_eingabefeld_den_fokus_nicht(self) -> None:
        app = _Probe(ansicht=ANSICHT_TABELLE)
        async with app.run_test(size=(120, 50)) as pilot:
            await _gefuellt(app, pilot)
            feld = app.query_one("#agenten-filter")
            feld.focus()
            await pilot.pause()
            app.query_one("#agenten", AgentenTabelle).ansicht_wechseln()
            await pilot.pause()
            assert app.focused is feld

    async def test_pfeile_bewegen_die_auswahl_in_zwei_richtungen(self) -> None:
        app = _Probe()
        async with app.run_test(size=(80, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            kacheln.focus()
            await pilot.pause()
            assert kacheln.styles.grid_size_columns == 3
            assert _markiert(kacheln) == ["Anna"]

            await pilot.press("right")
            await pilot.pause()
            assert _markiert(kacheln) == ["Bert"]
            assert app.ausgewaehlt[-1] == "Bert"

            await pilot.press("down")
            await pilot.pause()
            # Drei Spalten: eine Zeile tiefer sind drei Agenten weiter.
            assert _markiert(kacheln) == ["Emil"]
            markiert = app.query_one("#agenten", AgentenTabelle).markierter
            assert markiert is not None and markiert.name == "Emil"

            await pilot.press("end")
            await pilot.pause()
            assert _markiert(kacheln) == ["Gustav"]
            await pilot.press("home")
            await pilot.pause()
            assert _markiert(kacheln) == ["Anna"]

            # Am Rand bleibt sie stehen und springt nicht herum.
            await pilot.press("left")
            await pilot.pause()
            assert _markiert(kacheln) == ["Anna"]

    async def test_auswahl_ueberlebt_den_wechsel_der_ansicht(self) -> None:
        app = _Probe()
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            kacheln.focus()
            await pilot.press("right", "right")
            await pilot.pause()
            tabelle = app.query_one("#agenten", AgentenTabelle)
            tabelle.ansicht_wechseln()
            await pilot.pause()
            assert app.query_one("#agenten-daten", DataTable).cursor_row == 2
            assert tabelle.markierter is not None and tabelle.markierter.name == "Clara"

    async def test_klicks_tun_dasselbe_wie_in_der_tabelle(self) -> None:
        app = _Probe()
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            kachel = list(kacheln.query(AgentenKachel))[1]

            await pilot.click(kachel, button=3)
            await pilot.pause()
            assert app.menue == ["Bert"]
            assert _markiert(kacheln) == ["Bert"]

            zweite = list(kacheln.query(AgentenKachel))[2]
            await pilot.click(zweite, times=2)
            await pilot.pause()
            assert app.aufgerufen == ["Clara"]
            assert _markiert(kacheln) == ["Clara"]

    async def test_enter_ruft_auf(self) -> None:
        app = _Probe()
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            kacheln.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert app.aufgerufen == ["Anna"]

    async def test_filter_trifft_auch_die_kacheln(self) -> None:
        app = _Probe()
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            app.query_one("#agenten", AgentenTabelle).setze_filter("dora")
            await pilot.pause()
            await pilot.pause()
            assert [k.agent.name for k in kacheln.query(AgentenKachel)] == ["Dora"]
            assert _markiert(kacheln) == ["Dora"]

    async def test_neuer_bestand_baut_die_kacheln_nicht_neu(self) -> None:
        # Bei jedem Takt neu aufgebaut, flackerte die Ansicht und verlore den Scrollstand.
        app = _Probe()
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            vorher = list(kacheln.query(AgentenKachel))
            await _gefuellt(app, pilot)
            assert list(kacheln.query(AgentenKachel)) == vorher

    async def test_zwei_prozesse_auf_einer_sitzung_werfen_nicht(self) -> None:
        # Der Absturz vom 16.08.2026 in der Tabelle, siehe eindeutig().
        app = _Probe()
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot, ("Petra", "Petra"))
            assert len(kacheln.query(AgentenKachel)) == 2

    async def test_cursor_bleibt_im_bild(self) -> None:
        app = _Probe()
        async with app.run_test(size=(80, 20)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            kacheln.focus()
            await pilot.press("end")
            await pilot.pause()
            await pilot.pause()
            assert kacheln.scroll_y > 0
            letzte = list(kacheln.query(AgentenKachel))[-1]
            assert kacheln.region.contains_region(letzte.region)

    async def test_verborgene_ansicht_rechnet_nichts(self) -> None:
        app = _Probe(ansicht=ANSICHT_TABELLE)
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            assert kacheln._zeitgeber._active.is_set() is False
            app.query_one("#agenten", AgentenTabelle).ansicht_wechseln()
            await pilot.pause()
            assert kacheln._zeitgeber._active.is_set() is True

    async def test_nach_dem_einblenden_ist_jede_kachel_sichtbar(self) -> None:
        # Ein Zeitgeber mit Dauer null liess hier die erste Kachel unsichtbar stehen.
        app = _Probe(ansicht=ANSICHT_TABELLE)
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot)
            app.query_one("#agenten", AgentenTabelle).ansicht_wechseln()
            await pilot.pause()
            assert next(iter(kacheln.query(AgentenKachel))).styles.opacity < 1.0
            await pilot.pause(0.8)
            assert {k.styles.opacity for k in kacheln.query(AgentenKachel)} == {1.0}

    async def test_takt_zeichnet_nur_bei_aenderung(self) -> None:
        app = _Probe()
        async with app.run_test(size=(120, 50)) as pilot:
            kacheln = await _gefuellt(app, pilot, ("Anna",))
            kachel = next(iter(kacheln.query(AgentenKachel)))
            aufrufe: list[int] = []

            def gezaehlt(*_args: object, **_kwargs: object) -> AgentenKachel:
                aufrufe.append(1)
                return kachel

            kachel.refresh = gezaehlt  # type: ignore[method-assign,assignment]
            lidschlag = 32 * 5 - roboter.kennzahl("Anna") % 32
            kachel.ticken(lidschlag)
            assert len(aufrufe) == 1
            kachel.ticken(lidschlag + 1)  # Augen wieder auf
            assert len(aufrufe) == 2
            kachel.ticken(lidschlag + 2)  # nichts Neues
            assert len(aufrufe) == 2


class TestInDerAnwendung:
    @staticmethod
    def _app() -> ChatterdomeApp:
        app = ChatterdomeApp(quelle=FakeQuelle())  # type: ignore[arg-type]
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        return app

    async def test_f3_schaltet_um_und_merkt_es_sich(self) -> None:
        app = self._app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _app_gefuellt(app, pilot)
            kacheln = app.query_one("#agenten-kacheln", AgentenKacheln)
            assert not kacheln.display
            await pilot.press("f3")
            await pilot.pause()
            assert kacheln.display
            assert Einstellungen().laden()["agenten_ansicht"] == ANSICHT_KACHELN
            # 60 Prozent von 120 Zeichen reichen fuer drei Kacheln nebeneinander.
            assert kacheln.styles.grid_size_columns == 3

        # Der naechste Start beginnt, wo der letzte aufgehoert hat.
        wieder = self._app()
        async with wieder.run_test(size=(120, 40)) as pilot:
            await _app_gefuellt(wieder, pilot)
            assert wieder.query_one("#agenten-kacheln", AgentenKacheln).display

    async def test_filtertaste_bleibt_auf_dem_schraegstrich(self) -> None:
        app = self._app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _app_gefuellt(app, pilot)
            await pilot.press("slash")
            await pilot.pause()
            assert app.focused is app.query_one("#agenten-filter")

    async def test_von_einem_anderen_reiter_erst_zurueck(self) -> None:
        app = self._app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _app_gefuellt(app, pilot)
            bereiche = app.query_one("#bereiche", TabbedContent)
            bereiche.active = "tab-diskussion"
            await pilot.pause()
            await pilot.press("f3")
            await pilot.pause()
            assert bereiche.active == "tab-agenten"
            assert not app.query_one("#agenten-kacheln", AgentenKacheln).display

    async def test_auswahl_in_den_kacheln_erreicht_die_anwendung(self) -> None:
        # Beenden und Neustart lesen _gewaehlt. Zeigt die Kachel jemand anderen
        # als die Anwendung, traefe DEL den falschen Agenten.
        app = self._app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _app_gefuellt(app, pilot)
            await pilot.press("f3")
            await pilot.pause()
            kacheln = app.query_one("#agenten-kacheln", AgentenKacheln)
            kacheln.focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            await pilot.pause()
            assert app._gewaehlt is not None
            assert _markiert(kacheln) == [app._gewaehlt.name]
