"""Die Oberflaeche headless fahren.

Die Quelle wird ersetzt, damit der Test keinen laufenden Bus braucht - was
geprueft wird, ist die Verdrahtung: kommen die Daten in Tabelle, Kopf,
Statuszeile und Verlauf an, und reagieren die Tasten.
"""

from __future__ import annotations

import time as zeit_modul
from datetime import datetime, timedelta

import pytest
from textual.widgets import Button, DataTable, Input

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.modelle import Agent, Auftrag, Bestand, Ereignis, Namenspool
from claude_sanctuary.kern.protokolle import Quelle
from claude_sanctuary.tui import starter as starter_modul
from claude_sanctuary.tui.app import ABSENDER, SanctuaryApp
from claude_sanctuary.tui.screens.rundruf_screen import RundrufErgebnis, RundrufScreen
from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenTabelle
from claude_sanctuary.tui.widgets.verlauf_panel import VerlaufPanel


class FakeQuelle:
    """Antwortet aus dem Gedaechtnis und merkt sich, was gesendet wurde."""

    def __init__(self) -> None:
        self.gesendet: list[tuple[str, str, str, str]] = []
        self.verlauf_abfragen: list[tuple[str, str, str]] = []
        """Je Verlaufsabfrage Name, Sitzung und Startzeit."""

        self.gestoppt: list[str] = []
        self.fern_neugestartet: list[tuple[str, str, str]] = []
        self.mit_tokens: list[bool] = []
        """Je Abfrage, ob der Verbrauch mit angefordert wurde."""

        self.fotos: list[str] = []
        self.foto_pfad = ""
        self.foto_fehler = "kein Desktop"

        self.updates: list[tuple[str, str]] = []
        self.update_version = "2.1.220"
        self.update_fehler = ""

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
                    letzte_zeit="2026-08-04T12:54:00",
                    aufgabe="mach den /release",
                ),
                # selbst=True: die Sitzung, die die Oberflaeche bedient.
                # Der lange Auftragstext ist Absicht: er treibt die
                # Aufgabenspalte auf ihre volle Breite und macht damit den
                # Ernstfall messbar statt den bequemen Kurztext.
                Agent(
                    name="Lino",
                    status="busy",
                    rechner="TESTHOST",
                    tokens=500,
                    selbst=True,
                    aufgabe="Bitte alle Tests laufen lassen, danach den Release bauen",
                ),
            ],
        )

    def namen(self) -> Namenspool:
        return Namenspool(motiv="Heilige", namen=["Klara", "Agnes"], frei=["Agnes"])

    def verlauf(self, name: str, *, session_id: str = "", seit: str = "") -> list[Auftrag]:
        self.verlauf_abfragen.append((name, session_id, seit))
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

    def neustarten_fern(self, rechner: str, session_id: str, cwd: str = "") -> str:
        self.fern_neugestartet.append((rechner, session_id, cwd))
        return ""

    def bildschirmfoto(self, rechner: str = "") -> tuple[str, str]:
        self.fotos.append(rechner)
        return self.foto_pfad, self.foto_fehler

    def aktualisiere_claude(self, rechner: str = "", verfahren: str = "claude") -> tuple[str, str]:
        self.updates.append((rechner, verfahren))
        return self.update_version, self.update_fehler


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
            # "?" oeffnet die Hilfe in beiden Stilen, "h" nur noch im klassischen.
            await pilot.press("question_mark")
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
            app._schnellbefehl("status")
            await pilot.pause()
            assert "Zwischenstand" in app.query_one("#eingabe", Input).value
            assert quelle.gesendet == []

    async def test_kein_schnellbefehl_verlangt_einen_slash_befehl(self) -> None:
        """Bis zum 22.08.2026 gab es "/compact" als Schnellbefehl.

        Der konnte nie funktionieren: ein Slash-Befehl ist ein Bedienelement des
        Terminals, kein Werkzeug des Modells - Claude Code fuehrt ihn aus einer
        Peer-Nachricht grundsaetzlich nicht aus. Der Auftrag endete jedes Mal mit
        einer Absage. Was hier steht, muss ein Agent auch tun koennen.
        """
        from claude_sanctuary.tui.app import SCHNELLBEFEHLE

        for schluessel in SCHNELLBEFEHLE:
            text = t(f"quick.{schluessel}_text")
            assert "/" not in text, f"{schluessel}: {text}"

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
            assert werte["pool"] == "Heilige"
            assert werte["free"] == "1"


class TestAufgabenspalte:
    """Aufgabe und letzte Aktivitaet stehen auch in der Tabelle.

    Vorher waren sie nur in der Detailansicht zu sehen - fuer die Frage
    "woran haengt gerade wer" hiesse das, jede Zeile einzeln aufzumachen.
    """

    async def test_tabelle_zeigt_aufgabe_und_alter(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(200, 50)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            # Nach Post absteigend steht Klara oben.
            zeile = [str(zelle) for zelle in tabelle.get_row_at(0)]
            assert zeile[AgentenTabelle._AUFGABEN_SPALTE] == "mach den /release"
            # Der Wert selbst haengt am Kalender - geprueft wird nur, dass
            # ueberhaupt ein Alter dasteht und nicht der Strich fuer "nichts".
            assert zeile[AgentenTabelle._ZEIT_SPALTE] != "-"

    async def test_beide_spalten_sind_ohne_scrollen_zu_sehen(
        self, quelle: FakeQuelle
    ) -> None:
        """Der Punkt der Uebung: sichtbar, nicht hinter dem Seitwaerts-Scroll.

        Frueher standen beide Spalten am rechten Ende - bei 141 Zeichen
        Gesamtbreite und rund 70 sichtbaren war das dasselbe wie gar nicht da.
        """
        from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenDaten

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        # Bewusst schmal: 120 Zeichen sind ein normales Fenster.
        async with app.run_test(size=(120, 45)) as pilot:
            tabelle = await _gefuellt(app, pilot)
            for _ in range(20):
                await pilot.pause()
            daten = app.query_one("#agenten-daten", AgentenDaten)
            spalten = list(daten.columns.values())
            bis_ende_aufgabe = sum(
                s.get_render_width(daten)
                for s in spalten[: AgentenTabelle._ZEIT_SPALTE + 1]
            )
            assert bis_ende_aufgabe <= tabelle.size.width, (
                f"Aufgabe und Alter brauchen {bis_ende_aufgabe} Zeichen, "
                f"sichtbar sind {tabelle.size.width}"
            )

    async def test_voller_text_haengt_als_hinweis_an_der_zelle(
        self, quelle: FakeQuelle
    ) -> None:
        """Die Spalte ist gekuerzt - der volle Text muss erreichbar bleiben."""
        from textual.coordinate import Coordinate

        from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenDaten

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(200, 50)) as pilot:
            await _gefuellt(app, pilot)
            tabelle = app.query_one("#agenten-daten", AgentenDaten)
            tabelle.hover_coordinate = Coordinate(0, AgentenTabelle._AUFGABEN_SPALTE)
            await pilot.pause()
            assert tabelle.tooltip == "mach den /release"

            # Die Spalte zeigt nur das Alter - der genaue Zeitpunkt muss
            # trotzdem erreichbar bleiben, sonst geht er ganz verloren.
            tabelle.hover_coordinate = Coordinate(0, AgentenTabelle._ZEIT_SPALTE)
            await pilot.pause()
            assert tabelle.tooltip == "04.08.2026 12:54"

            # Ausserhalb der umgerechneten Spalten haengt kein Hinweis, sonst
            # wiederholt er nur, was die Zelle ohnehin zeigt.
            tabelle.hover_coordinate = Coordinate(0, 1)
            await pilot.pause()
            assert tabelle.tooltip is None

    def test_langer_auftrag_wird_gekuerzt(self) -> None:
        from claude_sanctuary.tui.widgets.agenten_tabelle import _aufgabe

        lang = "Bitte alle Tests laufen lassen und danach den Release bauen"
        gekuerzt = _aufgabe(lang, breite=40)
        assert len(gekuerzt) <= 40
        assert gekuerzt.endswith("...")
        # Zeilenumbrueche wuerden die Tabellenzeile sprengen.
        assert "\n" not in _aufgabe("erste Zeile\nzweite Zeile", breite=40)

    def test_alter_rechnet_gegen_einen_festen_bezug(self) -> None:
        """Der Bezugszeitpunkt wird uebergeben, nicht aus der Uhr gelesen.

        Sonst waere jede Erwartung hier eine Zeitbombe - richtig, bis die
        Minute umspringt.
        """
        from claude_sanctuary.tui.widgets.agenten_tabelle import _alter

        jetzt = datetime(2026, 8, 4, 13, 0).astimezone()

        def vor(minuten: int) -> str:
            return (jetzt - timedelta(minutes=minuten)).isoformat()

        assert _alter(vor(0), jetzt) == "gerade"
        assert _alter(vor(6), jetzt) == "6 min"
        assert _alter(vor(90), jetzt) == "1 h"
        assert _alter(vor(60 * 50), jetzt) == "2 d"
        assert _alter("", jetzt) == "-"
        assert _alter("kein Datum", jetzt) == "?"


class TestBildschirmfotoTaste:
    async def test_taste_p_nimmt_auf(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            await pilot.press("p")
            for _ in range(60):
                await pilot.pause()
                if quelle.fotos:
                    break
            # Klara laeuft auf dem eigenen Rechner - also ohne Ziel.
            assert quelle.fotos == [""]

    def test_textuals_eigener_screenshot_bleibt_unangetastet(self) -> None:
        """Der Aktionsname ``screenshot`` gehoert Textual.

        Dort speichert er ein SVG der Oberflaeche. Wer ihn hier ueberschreibt,
        nimmt der Befehlspalette diese Funktion weg - deshalb heisst die
        eigene Aktion ``bildschirmfoto``.
        """
        from textual.app import App

        assert SanctuaryApp.action_screenshot is App.action_screenshot
        assert hasattr(SanctuaryApp, "action_bildschirmfoto")


class TestProtokoll:
    def test_fake_erfuellt_die_schnittstelle(self, quelle: FakeQuelle) -> None:
        """Haelt die Attrappe mit dem Protokoll Schritt?

        Der Test prueft nichts zur Laufzeit - er zwingt mypy dazu. Genau
        diese Zuweisung hat gefehlt, als die Quelle um Parameter wuchs: die
        Attrappe kannte sie nicht, der TypeError entstand erst im Worker und
        wurde dort verschluckt. Die Tabelle blieb einfach leer.
        """
        geprueft: Quelle = quelle
        assert geprueft is quelle


class TestRundruf:
    """Nachricht an alle - die Auswahl der Empfaenger ist der heikle Teil."""

    def _screen(self, mit_operator: bool) -> RundrufScreen:
        agenten = [
            Agent(name="Klara", status="idle", rechner="TESTHOST"),
            Agent(name="Operator", status="idle", rechner="TESTHOST"),
            Agent(name="Franko", status="idle", rechner="SENZA"),
            Agent(name="Lino", status="idle", rechner="TESTHOST", selbst=True),
        ]
        screen = RundrufScreen(agenten, ["Operator"])
        self._mit_operator = mit_operator
        return screen

    def test_eigene_sitzung_bleibt_aussen_vor(self) -> None:
        # An sich selbst wird nie gesendet - der Auftrag laege im Eingang
        # genau der Sitzung, die ihn abschickt.
        namen = [a.name for a in self._screen(False)._empfaenger(False)]
        assert "Lino" not in namen

    def test_operator_nur_auf_wunsch(self) -> None:
        screen = self._screen(False)
        ohne = [a.name for a in screen._empfaenger(False)]
        mit = [a.name for a in screen._empfaenger(True)]
        assert ohne == ["Klara", "Franko"]
        assert "Operator" in mit

    def test_andere_rechner_sind_dabei(self) -> None:
        """Der springende Punkt: der Rundruf des Bus bleibt lokal.

        Deshalb schickt die Oberflaeche je Agent einen eigenen Auftrag mit
        dessen Rechner. Faellt SENZA hier heraus, ist genau der Fehler
        zurueck, an dem die Zustellung schon einmal gescheitert ist.
        """
        rechner = {a.rechner for a in self._screen(False)._empfaenger(False)}
        assert rechner == {"TESTHOST", "SENZA"}

    async def test_senden_erreicht_jeden_einzeln(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            ergebnis = RundrufErgebnis(
                "Bitte alle melden",
                [
                    Agent(name="Klara", status="idle", rechner="TESTHOST"),
                    Agent(name="Franko", status="idle", rechner="SENZA"),
                ],
            )
            app._rundruf_abgeschickt(ergebnis)
            for _ in range(60):
                await pilot.pause()

            assert len(quelle.gesendet) == 2
            # Der Rechner MUSS mitgehen, sonst sucht der Bus ihn per Mesh
            # (gemessen 1,4 s statt 0,1 s) - oder findet ihn gar nicht.
            assert ("Klara", "Bitte alle melden", "TESTHOST", ABSENDER) in quelle.gesendet
            assert ("Franko", "Bitte alle melden", "SENZA", ABSENDER) in quelle.gesendet


class TestNeustart:
    async def test_ohne_sitzungskennung_kein_neustart(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            # Die Attrappe liefert Agenten ohne session_id.
            app.action_restart_agent()
            await pilot.pause()
            assert quelle.gestoppt == []

    async def test_neustart_stoppt_und_setzt_fort(
        self, quelle: FakeQuelle, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gerufen: list[tuple[str, str]] = []

        def fake_resume(
            session_id: str, verzeichnis: str = "", einstellungen: object = None
        ) -> str:
            gerufen.append((session_id, verzeichnis))
            return ""

        monkeypatch.setattr(starter_modul, "starte_resume", fake_resume)
        monkeypatch.setattr(zeit_modul, "sleep", lambda _s: None)

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._neustart_ausfuehren("Klara", "sid-42", r"C:\Repos\test")
            for _ in range(60):
                await pilot.pause()

            assert quelle.gestoppt == ["Klara"]
            assert gerufen == [("sid-42", r"C:\Repos\test")]

    async def test_ferner_agent_geht_ueber_das_cli_des_zielrechners(
        self, quelle: FakeQuelle, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Von hier aus laesst sich auf einem fremden Rechner kein Fenster oeffnen.

        Der lokale Weg (stoppen + starte_resume) darf deshalb gar nicht erst
        anlaufen - sonst wuerde hier ein Fenster aufgehen statt dort.
        """
        lokal_gerufen: list[str] = []
        monkeypatch.setattr(
            starter_modul,
            "starte_resume",
            lambda sid, wd="", e=None: lokal_gerufen.append(sid) or "",  # type: ignore[func-returns-value]
        )
        monkeypatch.setattr(zeit_modul, "sleep", lambda _s: None)

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._neustart_ausfuehren("Petra", "sid-99", "/home/michael", "SENZA")
            for _ in range(60):
                await pilot.pause()

            assert quelle.fern_neugestartet == [("SENZA", "sid-99", "/home/michael")]
            assert quelle.gestoppt == [], "beendet wird auf dem Zielrechner, nicht von hier"
            assert lokal_gerufen == [], "sonst geht das Fenster auf dem falschen Rechner auf"


class TestAktualisierung:
    async def test_update_nimmt_verfahren_aus_den_einstellungen(
        self, quelle: FakeQuelle
    ) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._einstellungen.speichern({"update_verfahren": "npm"})
            app._update_starten("SENZA")
            for _ in range(60):
                await pilot.pause()
            assert quelle.updates == [("SENZA", "npm")]

    async def test_eigener_rechner_ohne_ziel(self, quelle: FakeQuelle) -> None:
        """Der eigene Rechner wird ohne Namen aufgerufen - sonst ginge es
        ueber ssh zu sich selbst, und das braucht einen Schluessel."""
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._update_starten("TESTHOST")
            for _ in range(60):
                await pilot.pause()
            assert quelle.updates == [("", "claude")]


class TestDialoge:
    """Oeffnen die neuen Dialoge ueberhaupt?

    Ein Fehler in compose() faellt sonst erst beim Anwender auf - die
    Oberflaeche zeigt dann nur den Fehlerdialog, und bei einem Fehler im
    Fehlerdialog gar nichts mehr.
    """

    async def test_einstellungen_zeigen_die_neuen_reiter(self, quelle: FakeQuelle) -> None:
        from textual.widgets import Select, TabPane, TextArea

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app.action_show_settings()
            for _ in range(40):
                await pilot.pause()
            reiter = {p.id for p in app.screen.query(TabPane)}
            assert {"tab-terminal", "tab-update"} <= reiter
            assert app.screen.query_one("#set-terminal", Select)
            assert app.screen.query_one("#set-terminal-vorbereitung", TextArea)
            assert app.screen.query_one("#set-update", Select)

    async def test_rundruf_zeigt_die_empfaenger(self, quelle: FakeQuelle) -> None:
        from textual.widgets import Static

        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app.action_broadcast()
            for _ in range(40):
                await pilot.pause()
            zeile = app.screen.query_one("#rundruf-ziele", Static)
            text = str(zeile.render())
            # Klara ist da, die eigene Sitzung Lino nicht.
            assert "Klara" in text
            assert "Lino" not in text


class ZweiPetrasQuelle(FakeQuelle):
    """Zwei Sitzungen mit demselben Namen auf verschiedenen Rechnern.

    Nachgestellt nach Michaels Screenshot vom 09.08.2026: die alte Petra auf
    RAINBOW hat offene Post und steht deshalb bei der Vorgabesortierung
    (Post absteigend) ganz oben.
    """

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        self.mit_tokens.append(tokens)
        return Bestand(
            rechner="RAINBOW",
            zeit="2026-08-09T04:50:00.000Z",
            agenten=[
                Agent(name="Petra", status="idle", rechner="RAINBOW", post=3),
                Agent(name="Petra", status="idle", rechner="SENZA", post=0),
            ],
        )


class TestAuswahlBeiGleichemNamen:
    """Der gemeldete Fehler: die Markierung sprang auf den falschen Petra.

    Ohne den Fix wird die Auswahl ueber den blossen Namen wiederhergestellt.
    Der erste Treffer ist Petra@RAINBOW - und der naechste Auftrag ging
    dorthin statt an das gewaehlte Petra@SENZA.
    """

    async def test_markierung_bleibt_nach_neuaufbau_auf_dem_gewaehlten(self) -> None:
        from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenTabelle

        quelle = ZweiPetrasQuelle()
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(200, 50)) as pilot:
            daten = await _gefuellt(app, pilot)
            widget = app.query_one("#agenten", AgentenTabelle)

            # Auf Petra@SENZA stellen - nicht auf die erste Zeile.
            senza = next(
                i for i, a in enumerate(widget._sichtbar) if a.rechner == "SENZA"
            )
            assert senza != 0, "der Aufbau soll den zweiten Petra treffen"
            daten.move_cursor(row=senza)
            await pilot.pause()
            assert widget.markierter is not None
            assert widget.markierter.rechner == "SENZA"

            # Genau das, was die Taktabfrage tut.
            widget.uebernehmen(quelle.bestand().agenten)
            await pilot.pause()

            assert widget.markierter is not None
            assert widget.markierter.rechner == "SENZA", (
                "die Markierung ist auf den gleichnamigen Agenten des anderen "
                "Rechners gesprungen"
            )


class ZweimalDerselbeQuelle(FakeQuelle):
    """Zweimal derselbe Name auf DEMSELBEN Rechner.

    Der Zustand vom 16.08.2026 auf senza: ein Neustart hatte den alten Prozess
    nicht beendet, zwei Prozesse lagen auf derselben Sitzungskennung - und
    weil der Name an der Kennung haengt, trugen beide denselben. Die Tabelle
    baut ihre Zeilenkennung aus Rechner und Name, und ``add_row`` wirft bei
    einer doppelten ``DuplicateKey``.
    """

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        self.mit_tokens.append(tokens)
        return Bestand(
            rechner="RAINBOW",
            zeit="2026-08-16T00:19:00.000Z",
            agenten=[
                Agent(name="Operator", status="idle", rechner="SENZA", session_id="sid-1"),
                Agent(name="Operator", status="idle", rechner="SENZA", session_id="sid-1"),
            ],
        )


class TestDoppelterAgentReisstNichtsMit:
    async def test_beide_zeilen_stehen_da_und_die_app_lebt(self) -> None:
        """Nicht entdoppeln: zwei Prozesse auf einer Sitzung soll man SEHEN.

        Vor dem Fix starb die App an dieser Stelle - und zwar aus dem
        Neuaufbau heraus, der im Sekundentakt laeuft. Der Absturzschirm fing
        es ab, der naechste Durchlauf warf es erneut.
        """
        app = SanctuaryApp(quelle=ZweimalDerselbeQuelle())
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            daten = await _gefuellt(app, pilot)
            assert daten.row_count == 2
            assert app.is_running


class TestQImBrowser:
    """Im Browser beendete q die ganze Sitzung (Michaels Test am 15.09.2026)."""

    async def test_q_beendet_im_browser_nicht(
        self, quelle: FakeQuelle, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(SanctuaryApp, "is_web", property(lambda self: True))
        meldungen: list[str] = []
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        monkeypatch.setattr(app, "notify", lambda text, **_: meldungen.append(str(text)))
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            await pilot.press("q")
            await pilot.pause()
            assert app.is_running
            assert meldungen == [t("notify.web_quit")]

    async def test_gegenprobe_im_terminal_beendet_q(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            await pilot.press("q")
            await pilot.pause()
            assert not app.is_running


class TestVerlaufNachSendenUndRundruf:
    """Nach dem Senden wurde der Verlauf mit dem NAMEN nachgeladen.

    Belegt am 16.09.2026 auf senza: der Worker starb mit
    ``AttributeError: 'str' object has no attribute 'laufzeit_ms'``, sobald ein
    Auftrag abgelegt war. mypy sieht solche Aufrufe nicht - ``@work`` macht die
    Methode fuer die Pruefung untypisiert.
    """

    async def test_senden_uebergibt_den_agenten(
        self, quelle: FakeQuelle, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Geprueft wird die AUFRUFSTELLE, nicht die Wirkung: verlauf_laden ist
        # ein Worker, und beim Fuellen der Tabelle laeuft ohnehin schon eine
        # Verlaufsabfrage - die traegt sonst einen Eintrag nach, egal was die
        # Aufrufstelle uebergibt. Genau daran war der erste Anlauf dieses
        # Tests blind.
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            gerufen: list[object] = []
            monkeypatch.setattr(app, "verlauf_laden", gerufen.append)
            app._senden_fertig("Klara", "")
            assert gerufen, "nach dem Senden wurde der Verlauf nicht nachgeladen"
            assert isinstance(gerufen[-1], Agent), f"Name statt Agent: {gerufen[-1]!r}"

    async def test_rundruf_uebergibt_den_agenten(
        self, quelle: FakeQuelle, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            gerufen: list[object] = []
            monkeypatch.setattr(app, "verlauf_laden", gerufen.append)
            app._rundruf_fertig(1, [])
            assert gerufen, "nach dem Rundruf wurde der Verlauf nicht nachgeladen"
            assert isinstance(gerufen[-1], Agent), f"Name statt Agent: {gerufen[-1]!r}"


class TestAuswahlBeimAbbau:
    """Eine Auswahl-Nachricht darf nach dem Abbau der Eingabe nichts umreissen.

    Belegt in der CI (windows-latest, Python 3.12) am 15.09.2026: beim Beenden
    kam ``AgentenTabelle.Ausgewaehlt`` noch an, als ``#eingabe`` schon weg war.
    """

    async def test_fehlende_eingabe_bricht_den_handler_nicht(self, quelle: FakeQuelle) -> None:
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        agent = Agent(name="Klara", status="idle", rechner="TESTHOST")
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            await app.query_one("#eingabe", Input).remove()
            await pilot.pause()
            app.on_agenten_tabelle_ausgewaehlt(AgentenTabelle.Ausgewaehlt(agent))
            assert app._gewaehlt is agent
            assert app.is_running


class SitzungsQuelle(FakeQuelle):
    """Ein Agent mit Sitzung und Laufzeit, wie ihn der echte Status liefert."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        self.mit_tokens.append(tokens)
        return Bestand(
            rechner="TESTHOST",
            zeit="2026-09-15T18:00:00.000Z",
            agenten=[
                Agent(
                    name="Charlene",
                    status="idle",
                    rechner="TESTHOST",
                    session_id="sid-neu",
                    laufzeit_ms=3_600_000,
                )
            ],
        )


class TestVerlaufHaengtAnDerSitzung:
    """Am 15.09.2026 stand unter Charlene der Verlauf einer frueheren Sitzung."""

    async def test_die_abfrage_nennt_sitzung_und_startzeit(self) -> None:
        quelle = SitzungsQuelle()
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            for _ in range(60):
                await pilot.pause()
            assert ("Charlene", "sid-neu", "2026-09-15T17:00:00+00:00") in quelle.verlauf_abfragen


class NochLaufendQuelle(FakeQuelle):
    """Der Stop kommt durch, der Prozess bleibt trotzdem stehen."""

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        self.mit_tokens.append(tokens)
        return Bestand(
            rechner="TESTHOST",
            zeit="2026-08-16T00:19:00.000Z",
            agenten=[
                Agent(name="Klara", status="idle", rechner="TESTHOST", session_id="sid-42")
            ],
        )


class TestKeinZweitesFensterAufEinemGespraech:
    """Warten statt raten - hier stand ein festes ``sleep(1.5)``.

    Wer das Fenster oeffnet, waehrend der alte Prozess noch lebt, bekommt zwei
    Sitzungen auf einem Transkript. Genau dieser Zustand lag am 16.08.2026 auf
    senza vor, dort ueber den fernen Weg.
    """

    async def test_ohne_beendeten_prozess_kein_resume(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gerufen: list[str] = []
        monkeypatch.setattr(
            starter_modul,
            "starte_resume",
            lambda sid, wd="", e=None: gerufen.append(sid) or "",  # type: ignore[func-returns-value]
        )
        monkeypatch.setattr(zeit_modul, "sleep", lambda _s: None)

        quelle = NochLaufendQuelle()
        app = SanctuaryApp(quelle=quelle)
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        # Ohne die kurze Frist wartete der Test acht Sekunden auf sein Ergebnis.
        monkeypatch.setattr(SanctuaryApp, "STERBEFRIST", 0.2)
        async with app.run_test(size=(160, 50)) as pilot:
            await _gefuellt(app, pilot)
            app._neustart_ausfuehren("Klara", "sid-42", r"C:\Repos\test")
            for _ in range(120):
                await pilot.pause()

            assert quelle.gestoppt == ["Klara"]
            assert gerufen == [], "sonst laufen zwei Sitzungen auf einem Gespraech"
