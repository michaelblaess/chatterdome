"""Die Zentrale als Textual-Oberflaeche."""

from __future__ import annotations

import contextlib
import dataclasses
import time
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Footer, Header, Input, TabbedContent, TabPane
from textual_themes import THEME_DISPLAY_NAMES, register_all
from textual_widgets import (
    DISCLAIMER_VERSION,
    AboutScreen,
    ClearableInput,
    ClickableLinksMixin,
    CrashGuard,
    DisclaimerScreen,
    DisclaimerStore,
    HorizontalSplitter,
    LogPanel,
    LogRouter,
    VerticalSplitter,
)

from claude_sanctuary import __author__, __version__, __year__
from claude_sanctuary.i18n import current_language, t
from claude_sanctuary.kern import absturz
from claude_sanctuary.kern.einstellungen import ZUSTIMMUNG, Einstellungen
from claude_sanctuary.kern.gedaechtnis import (
    Gedaechtnis,
    Notiz,
    Recallbericht,
    lade_gedaechtnis,
    uebernimm_recalls,
    zaehle_recalls,
)
from claude_sanctuary.kern.lokale_quelle import LokaleQuelle
from claude_sanctuary.kern.modelle import (
    Agent,
    Auftrag,
    Bestand,
    Busbestand,
    Namenspool,
    startzeit,
)
from claude_sanctuary.kern.protokolle import Quelle
from claude_sanctuary.kern.statistik import Statistik, lade_statistik
from claude_sanctuary.kern.suche import Bilanz, Suchindex
from claude_sanctuary.kern.terminals import finde
from claude_sanctuary.tui import keymap
from claude_sanctuary.tui.schutz import klartext
from claude_sanctuary.tui.starter import oeffne_ordner
from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenTabelle
from claude_sanctuary.tui.widgets.bus_detail import BusDetail
from claude_sanctuary.tui.widgets.bus_tabelle import BusTabelle
from claude_sanctuary.tui.widgets.gedaechtnis_detail import GedaechtnisDetail
from claude_sanctuary.tui.widgets.kopf_panel import KopfPanel
from claude_sanctuary.tui.widgets.notizen_tabelle import NotizenTabelle
from claude_sanctuary.tui.widgets.statistik_dashboard import StatistikDashboard
from claude_sanctuary.tui.widgets.status_zeile import StatusZeile
from claude_sanctuary.tui.widgets.such_panel import SuchPanel
from claude_sanctuary.tui.widgets.verlauf_panel import Blase, VerlaufPanel

ABSENDER = "Sanctuary"
"""Absendername der Auftraege aus dieser Oberflaeche.

Sie ist keine Claude-Sitzung und hat deshalb keine Session-ID, aus der der
Bus sonst den Namen zieht. Ohne die Angabe stand in jedem Auftrag "unbekannt".
"""

SCHNELLBEFEHLE = ("status", "pause", "done")
"""Vorformulierte Auftragstexte.

Sie fuellen NUR das Eingabefeld - abgeschickt wird weiter bewusst.

HIER STEHT NUR, WAS EIN AGENT AUCH TUN KANN. Bis zum 22.08.2026 gab es einen
Schnellbefehl "/compact", und der konnte nie funktionieren: ein Slash-Befehl
ist ein Bedienelement des Terminals, kein Werkzeug des Modells. Anthropics Doku
sagt es fuer Peer-Nachrichten ausdruecklich - "a command in the message's text,
such as /compact, arrives as plain text. Claude Code never executes it" - und
das gilt auch ueber den Inbox-Socket. Der Auftrag endete deshalb jedes Mal mit
einer Absage. Ausloesen kann /compact nur ein Mensch im Zielfenster.
"""


def _bus_datei() -> Path:
    """Pfad der Bus-Datenbank dieses Rechners."""
    import platform

    rechner = platform.node().upper() or "UNBEKANNT"
    return Path.home() / ".claude" / "bus" / rechner / "bus.db"


def _nur_hier(beschriftung: str, moeglich: bool) -> str:
    """Haengt den Grund an, wenn ein Menueeintrag nur lokal geht.

    Ein ausgegrauter Eintrag ohne Begruendung ist ein Raetsel: Michael hielt
    "Agent neu starten" am 14.08.2026 fuer fehlend, weil es bei einem Agenten
    auf einem anderen Rechner grau dastand. Der Grund gehoert an die
    Beschriftung, sonst sucht man ihn im Code.
    """
    return beschriftung if moeglich else f"{beschriftung} ({t('menu.only_here')})"


class SanctuaryApp(CrashGuard, ClickableLinksMixin, LogRouter, App[None]):  # type: ignore[misc]
    """Beobachtet die laufenden Sitzungen und verteilt Auftraege."""

    CSS_PATH = "app.tcss"
    TITLE = "Claude Sanctuary"

    # Keine Klassen-BINDINGS: die Belegung haengt am gewaehlten Stil, und der
    # steht erst fest, wenn die Einstellungen geladen sind. Siehe tui/keymap.py.

    def __init__(self, quelle: Quelle | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        register_all(self)
        self._einstellungen = Einstellungen()
        werte = self._einstellungen.laden()
        self._keymap_vim = keymap.vim_from_settings(werte)
        self._keymap_stil = keymap.style_from_settings(werte)
        self._keymap_ergebnis = keymap.resolve(werte)
        self._tasten_binden()
        self._nur_lokal = bool(werte.get("nur_lokal", False))
        self._takt = max(2, int(werte.get("aktualisierung_sekunden", 5)))
        # Composition Root: hier wird verdrahtet. Der Parameter erlaubt es,
        # im Test eine Quelle ohne laufenden Bus einzusetzen.
        self._quelle: Quelle = quelle if quelle is not None else LokaleQuelle()
        self._disclaimer = DisclaimerStore(ZUSTIMMUNG)
        self._bestand = Bestand(rechner="", zeit="")
        self._gewaehlt: Agent | None = None
        self._stop_kandidat = ""
        self._menue_ziel: Agent | None = None
        self._verlauf_blase: Blase | None = None
        """Die Blase, auf der das Verlaufsmenue geoeffnet wurde."""

        self._letzter_speicherort = str(Path.home())
        """Startordner des Speichern-Dialogs, zieht mit dem letzten Ziel mit."""

        self._letzte_fehler: list[str] = []
        self._verbrauch: int | None = None
        """Zuletzt ermittelter Verbrauch. None, solange nie abgefragt."""

        self._bild_rechner = ""
        self._bild_pfad = ""

        self._reserviert: list[str] = []
        """Namen aus dem Pool, die vorab vergeben sind - fuer den Rundruf."""

        self._gedaechtnis: Gedaechtnis | None = None
        """Der Notizbestand. None, solange der Tab nie geoeffnet wurde."""

        self._notiz: Notiz | None = None

        self._busbestand: Busbestand | None = None
        """Was im Bus liegt. None, solange der Tab nie geoeffnet wurde."""

        self._auftrag: Auftrag | None = None

        self._statistik: Statistik | None = None
        self._suchindex = Suchindex()
        self._index_gebaut = False
        self._index_laeuft = False
        """Die Auswertung. None, solange der Tab nie geoeffnet wurde."""

        self._neustart_kandidat: Agent | None = None
        self._gemeldete_systeme: dict[str, str] = {}
        self._start = time.monotonic()
        self._laeuft = False
        with contextlib.suppress(Exception):
            self.theme = str(werte.get("theme", "textual-dark"))

    # -- Aufbau ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield KopfPanel(_bus_datei(), id="kopf")
        with TabbedContent(id="bereiche"):
            with TabPane(t("tab.agents"), id="tab-agenten"), Horizontal(id="agenten-raum"):
                yield AgentenTabelle(id="agenten")
                yield VerticalSplitter(target_id="agenten", min_size=40, id="mitte-splitter")
                with Vertical(id="verlauf-raum"):
                    yield VerlaufPanel(id="verlauf")
                    yield HorizontalSplitter(target_id="verlauf", min_size=5, id="eingabe-splitter")
                    with Vertical(id="eingabe-raum"):
                        # input_id="eingabe": das innere Feld behaelt die ID,
                        # damit query_one("#eingabe", Input) ueberall gilt.
                        yield ClearableInput(
                            placeholder=t("chat.placeholder_none"),
                            tooltip=t("chat.clear"),
                            input_id="eingabe",
                            id="eingabe-zeile",
                        )
                        with Horizontal(id="schnellbefehle"):
                            yield Button(t("chat.send"), variant="primary", id="senden")
                            for schluessel in SCHNELLBEFEHLE:
                                yield Button(
                                    t(f"quick.{schluessel}"),
                                    variant="default",
                                    id=f"quick-{schluessel}",
                                    classes="schnell",
                                )
            with TabPane(t("tab.bus"), id="tab-bus"), Horizontal(id="bus-raum"):
                yield BusTabelle(id="bus-liste")
                yield VerticalSplitter(target_id="bus-liste", min_size=50, id="bus-splitter")
                yield BusDetail(id="bus-detail")
            with TabPane(t("tab.stats"), id="tab-statistik"):
                yield StatistikDashboard(id="statistik")
            with TabPane(t("tab.search"), id="tab-suche"):
                yield SuchPanel(id="suche")
            with (
                TabPane(t("tab.memory"), id="tab-gedaechtnis"),
                Horizontal(id="gedaechtnis-raum"),
            ):
                yield NotizenTabelle(id="notizen")
                yield VerticalSplitter(target_id="notizen", min_size=40, id="notizen-splitter")
                yield GedaechtnisDetail(id="gedaechtnis-detail")
        yield StatusZeile(id="status")
        yield HorizontalSplitter(target_id="bereiche", min_size=8, id="log-splitter")
        yield LogPanel(lang=current_language(), export_name="claude-sanctuary", id="log")
        yield Footer()

    def on_mount(self) -> None:
        self._binding_texte()
        self._schreibe_log(t("log.started", version=__version__))
        # Erst hier gemeldet: beim Binden gab es das Log noch nicht.
        for problem in self._keymap_ergebnis.problems:
            self._schreibe_log(f"[!] {problem.message}")
        self._theme_melden()
        self.set_interval(self._takt, self._takt_abfrage)
        self.aktualisieren()
        self.namen_laden()
        self._frage_disclaimer()

    def _binding_texte(self) -> None:
        """Setzt Beschriftung und Tooltip der Bindings zur Laufzeit.

        ``BindingsMap.bind()`` nimmt kein Tooltip-Argument, deshalb hier per
        ``dataclasses.replace``. Die Beschriftung wird mit gesetzt, damit ein
        spaeter geladenes Sprachpaket auch den Footer erreicht.
        """
        for taste, liste in self._bindings.key_to_bindings.items():
            for i, binding in enumerate(liste):
                beschriftung = keymap.LABEL_KEYS.get(binding.action)
                if beschriftung is None:
                    continue
                tooltip = keymap.TOOLTIP_KEYS.get(binding.action)
                self._bindings.key_to_bindings[taste][i] = dataclasses.replace(
                    binding,
                    description=t(beschriftung),
                    tooltip=t(tooltip) if tooltip else binding.tooltip,
                )

    def _tasten_binden(self) -> None:
        """Bindet die Tasten der aktiven Belegung, siehe ``tui/keymap.py``."""
        for action, binding in self._keymap_ergebnis.bindings.items():
            self._bindings.bind(
                ",".join(binding.keys),
                action,
                t(keymap.LABEL_KEYS.get(action, action)),
                key_display=keymap.key_display(binding.keys[0]),
                show=binding.show,
                priority=binding.priority,
            )

    @property
    def vim_navigation(self) -> bool:
        """Ob die Tabellen die Vim-Ebene bekommen. Sie fragen das beim Einhaengen ab."""
        return self._keymap_vim

    def tastenhinweis(self, action: str) -> str:
        """Die Taste einer Aktion, so wie sie in einer Meldung stehen soll."""
        return keymap.key_hint(self._keymap_ergebnis.bindings, action)

    def _frage_disclaimer(self) -> None:
        if self._disclaimer.accepted_version == DISCLAIMER_VERSION:
            return
        self.push_screen(
            DisclaimerScreen(
                app_name=f"claude-sanctuary {__version__}",
                lang=current_language(),
                author=__author__,
                title=t("disclaimer.title"),
                intro=t("disclaimer.intro"),
                duties=(
                    t("disclaimer.duty_authorisation"),
                    t("disclaimer.duty_actions"),
                    t("disclaimer.duty_data"),
                ),
                footer=f"© {__year__} {__author__} · github.com/michaelblaess/claude-sanctuary",
            ),
            callback=self._disclaimer_beantwortet,
        )

    def _disclaimer_beantwortet(self, angenommen: bool | None) -> None:
        if not angenommen:
            self.exit()
            return
        self._disclaimer.record()

    # -- Abfrage --------------------------------------------------------

    def _takt_abfrage(self) -> None:
        if not self._laeuft:
            self.aktualisieren()

    @work(thread=True, exclusive=True, group="abfrage")
    def aktualisieren(self, tokens: bool = False) -> None:
        """Holt den Bestand. Laeuft im Thread, weil der Unterprozess blockiert."""
        self._laeuft = True
        try:
            bestand = self._quelle.bestand(mesh=not self._nur_lokal, tokens=tokens)
        finally:
            self._laeuft = False
        self.call_from_thread(self._bestand_uebernehmen, bestand, tokens)

    def _bestand_uebernehmen(self, bestand: Bestand, verbrauch: bool = False) -> None:
        self._bestand = bestand
        # Den Wert MERKEN, nicht nur ein Sichtbar-Flag setzen: die naechste
        # Taktabfrage laeuft ohne --tokens und liefert wieder 0. Wer nur ein
        # Flag setzt, zeigt ab dann eine Null als waere sie gemessen.
        if verbrauch:
            self._verbrauch = bestand.tokens
        laufzeit = int((time.monotonic() - self._start) * 1000)
        self.query_one("#kopf", KopfPanel).uebernehmen(
            bestand, nur_lokal=self._nur_lokal, laufzeit_ms=laufzeit
        )
        self.query_one("#agenten", AgentenTabelle).uebernehmen(bestand.agenten)
        self.query_one("#status", StatusZeile).uebernehmen(bestand, verbrauch=self._verbrauch)

        # Betriebssystem je Rechner einmalig ins Protokoll - dauerhaft in
        # der Tabelle waere es eine Spalte, die in jeder Zeile dasselbe sagt.
        neu = {r: s for r, s in bestand.systeme.items() if self._gemeldete_systeme.get(r) != s}
        for rechner, system in neu.items():
            self._schreibe_log(t("log.systems", rechner=rechner, system=system))
        self._gemeldete_systeme.update(neu)

        # Nur bei Aenderung melden. Ein dauerhaft offline stehender Rechner
        # wuerde sonst im Sekundentakt dieselbe Zeile schreiben und das
        # Protokoll unbrauchbar machen.
        if bestand.fehler != self._letzte_fehler:
            for meldung in bestand.fehler:
                self._schreibe_log(t("log.refresh_failed", fehler=meldung), "warning")
            self._letzte_fehler = list(bestand.fehler)

    # -- Gedaechtnis ----------------------------------------------------

    @work(thread=True, exclusive=True, group="gedaechtnis")
    def gedaechtnis_laden(self, mit_abrufen: bool = True) -> None:
        """Liest die Notizen und danach die Abrufe aus den Transkripten.

        Beides im Thread: das Lesen der Notizen dauert bei kaltem
        Zwischenspeicher rund zwei Sekunden, der Durchgang durch die
        Transkripte je nach Bestand deutlich laenger. Die Tabelle steht
        deshalb schon, bevor die Abrufe gezaehlt sind.
        """
        bestand = lade_gedaechtnis(self._gedaechtnis_pfad())
        self.call_from_thread(self._gedaechtnis_uebernehmen, bestand)
        if not mit_abrufen or not bestand.notizen:
            return
        bericht = zaehle_recalls(Path.home() / ".claude" / "projects", bestand.alle_namen())
        self.call_from_thread(self._abrufe_uebernehmen, bericht)

    def _gedaechtnis_pfad(self) -> Path:
        eigen = str(self._einstellungen.laden().get("gedaechtnis_pfad", "")).strip()
        return Path(eigen) if eigen else Path.home() / ".claude" / "memory"

    def _gedaechtnis_uebernehmen(self, bestand: Gedaechtnis) -> None:
        self._gedaechtnis = bestand
        self.query_one("#notizen", NotizenTabelle).uebernehmen(bestand.notizen)
        detail = self.query_one("#gedaechtnis-detail", GedaechtnisDetail)
        detail.setze_bestand(bestand)
        detail.setze_laeuft(bool(bestand.notizen))
        if not bestand.notizen:
            self._schreibe_log(
                t("log.memory_missing", pfad=str(self._gedaechtnis_pfad())), "warning"
            )
            return
        self._schreibe_log(
            t("log.memory_loaded", anzahl=bestand.anzahl, zeilen=bestand.index_zeilen)
        )

    def _abrufe_uebernehmen(self, bericht: Recallbericht) -> None:
        if self._gedaechtnis is None:
            return
        uebernimm_recalls(self._gedaechtnis, bericht)
        detail = self.query_one("#gedaechtnis-detail", GedaechtnisDetail)
        detail.setze_laeuft(False)
        # Die Tabelle traegt die Abrufe in einer eigenen Spalte, sie muss also
        # neu gebaut werden - die Auswahl bleibt dabei stehen.
        self.query_one("#notizen", NotizenTabelle).uebernehmen(self._gedaechtnis.notizen)
        detail.setze_bestand(self._gedaechtnis)
        self._schreibe_log(
            t("log.memory_recalls", zugeordnet=bericht.zugeordnet, dateien=bericht.dateien)
        )

    def on_notizen_tabelle_ausgewaehlt(self, ereignis: NotizenTabelle.Ausgewaehlt) -> None:
        self._notiz = ereignis.notiz
        self.query_one("#gedaechtnis-detail", GedaechtnisDetail).setze_notiz(ereignis.notiz)

    def on_tabbed_content_tab_activated(self, ereignis: TabbedContent.TabActivated) -> None:
        """Laedt einen Tab beim ersten Oeffnen.

        Wer den Tab nie oeffnet, zahlt den Durchgang durch die Transkripte
        auch nicht.
        """
        if ereignis.pane.id == "tab-gedaechtnis" and self._gedaechtnis is None:
            self.gedaechtnis_laden()
        elif ereignis.pane.id == "tab-bus" and self._busbestand is None:
            self.bus_laden()
        elif ereignis.pane.id == "tab-suche":
            self.index_vorbereiten()
        elif ereignis.pane.id == "tab-statistik" and self._statistik is None:
            self.query_one("#statistik", StatistikDashboard).setze_laeuft(True)
            self.statistik_laden()

    def action_show_memory(self) -> None:
        """Zeigt den Gedaechtnis-Tab und liest den Bestand neu ein."""
        self.query_one("#bereiche", TabbedContent).active = "tab-gedaechtnis"
        self.gedaechtnis_laden()

    # -- Volltextsuche --------------------------------------------------

    def action_show_search(self) -> None:
        """Zeigt den Suchreiter und setzt den Cursor gleich ins Eingabefeld."""
        self.query_one("#bereiche", TabbedContent).active = "tab-suche"
        self.index_vorbereiten()
        self.query_one("#suche", SuchPanel).fokussiere()

    def index_vorbereiten(self) -> None:
        """Startet den Aufbau genau einmal.

        Der Reiter hat zwei Wege hinein - das Tastenkuerzel und der Wechsel per
        Maus. Der Wechsel loest ``TabActivated`` aus, das Kuerzel ebenfalls,
        weil es den Reiter setzt. Ohne diesen Riegel liefen zwei Aufbauten
        gleichzeitig.

        Das ist NICHT die bekannte Falle "exclusive=True plus eigener Guard":
        dort blockiert ein Merker den Nachfolger eines abgebrochenen Laufs.
        Hier wird nie abgebrochen und nie wiederholt - der Index wird einmal
        gebaut, danach steht ``_index_gebaut``.
        """
        if self._index_gebaut or self._index_laeuft:
            return
        self._index_laeuft = True
        self.index_bauen()

    @work(thread=True, exclusive=True, group="suchindex")
    def index_bauen(self) -> None:
        """Bringt den Suchindex auf Stand.

        Im Thread, weil der erste Lauf ueber den ganzen Bestand geht - gemessen
        1,8 s fuer 98 Transkripte. Jeder weitere Lauf fasst nur an, was sich
        geaendert hat, und ist damit unter einer Hundertstelsekunde durch.
        """
        panel = self.query_one("#suche", SuchPanel)

        def melde(erledigt: int, gesamt: int) -> None:
            self.call_from_thread(panel.zeige_aufbau, erledigt, gesamt)

        try:
            bilanz = self._suchindex.aktualisiere(melde=melde)
            dateien, stuecke = self._suchindex.bestand()
        except Exception:
            # Ohne das bliebe der Merker stehen und der Reiter dauerhaft leer.
            self.call_from_thread(self._index_gescheitert)
            raise
        self.call_from_thread(self._index_fertig, bilanz, dateien, stuecke)

    def _index_gescheitert(self) -> None:
        self._index_laeuft = False

    def _index_fertig(self, bilanz: Bilanz, dateien: int, stuecke: int) -> None:
        self._index_gebaut = True
        self._index_laeuft = False
        self.query_one("#suche", SuchPanel).zeige_bestand(bilanz, dateien, stuecke)
        # Nur melden, wenn wirklich etwas passiert ist - ein Lauf ohne Aenderung
        # ist der Regelfall und gehoert nicht ins Protokoll.
        if bilanz.neu or bilanz.aktualisiert or bilanz.entfernt:
            self._schreibe_log(
                t(
                    "log.index_done",
                    dateien=dateien,
                    neu=bilanz.neu,
                    aktualisiert=bilanz.aktualisiert,
                    entfernt=bilanz.entfernt,
                    s=f"{bilanz.dauer_s:.1f}",
                )
            )

    def on_such_panel_suche_geaendert(self, ereignis: SuchPanel.SucheGeaendert) -> None:
        """Beantwortet eine Eingabe. Laeuft im Ereignisstrang - 1 bis 2 ms."""
        panel = self.query_one("#suche", SuchPanel)
        panel.zeige(self._suchindex.suche(ereignis.text), ereignis.text)

    def on_such_panel_treffer_gewaehlt(self, ereignis: SuchPanel.TrefferGewaehlt) -> None:
        """Oeffnet das Transkript hinter einem Treffer im zustaendigen Programm.

        Ein eigener Transkriptleser waere der naechste Schritt - bis dahin ist
        die Datei selbst der ehrlichste Weg: sie ist da, sie ist lesbar, und
        niemand muss einen Pfad abtippen. Geoeffnet wird ueber die Mechanik des
        ClickableLinksMixin, damit es nur EINE plattformabhaengige Stelle gibt.
        """
        self._link_counter += 1
        self._link_registry[self._link_counter] = str(ereignis.treffer.pfad)
        self.action_open_link(str(self._link_counter))

    # -- Message-Bus ----------------------------------------------------

    @work(thread=True, exclusive=True, group="busbestand")
    def bus_laden(self) -> None:
        """Liest den gesamten Busbestand.

        Im Thread, weil dahinter ein Prozessstart steckt - unter Windows
        allein dafuer 70 bis 105 ms, dazu das Lesen der Datenbank.
        """
        bestand = self._quelle.bestandsverlauf()
        self.call_from_thread(self._bus_uebernehmen, bestand)

    def _bus_uebernehmen(self, bestand: Busbestand) -> None:
        self._busbestand = bestand
        detail = self.query_one("#bus-detail", BusDetail)
        detail.setze_laeuft(False)
        detail.setze_bestand(bestand)
        # Nach dem Detail: die Tabelle meldet ihren gefilterten Ausschnitt
        # zurueck, und der soll den soeben gesetzten Gesamtbestand ueberschreiben.
        self.query_one("#bus-liste", BusTabelle).uebernehmen(bestand.auftraege)
        if bestand.fehler:
            self._schreibe_log(t("log.bus_failed", fehler=bestand.fehler), "error")
            return
        self._schreibe_log(t("log.bus_loaded", anzahl=len(bestand.auftraege)))

    def on_bus_tabelle_ausgewaehlt(self, ereignis: BusTabelle.Ausgewaehlt) -> None:
        self._auftrag = ereignis.auftrag
        self.query_one("#bus-detail", BusDetail).setze_auftrag(ereignis.auftrag)

    def on_bus_tabelle_filter_geaendert(self, ereignis: BusTabelle.FilterGeaendert) -> None:
        # Die Kennzahlen rechts zeigen den SICHTBAREN Ausschnitt. Wer filtert,
        # will wissen, was in diesem Ausschnitt offen ist - nicht im Ganzen.
        self.query_one("#bus-detail", BusDetail).setze_sichtbar(ereignis.sichtbar)

    def action_show_bus(self) -> None:
        """Zeigt den Bus-Tab und liest den Bestand neu ein."""
        self.query_one("#bereiche", TabbedContent).active = "tab-bus"
        self.bus_laden()

    # -- Statistik ------------------------------------------------------

    @work(thread=True, exclusive=True, group="statistik")
    def statistik_laden(self) -> None:
        """Wertet Transkripte und Bus aus.

        Im Thread, weil der Durchgang durch die Transkripte gemessen 2,3 s
        dauert (369 MB). Der Busbestand kommt aus derselben Quelle wie im
        Bus-Tab - er wird hier eigens geholt, damit der Statistik-Tab auch
        ohne vorher geoeffneten Bus-Tab vollstaendig ist.
        """
        bus = self._quelle.bestandsverlauf()
        # Die laufenden Sitzungen kommen aus dem zuletzt geholten Bestand statt
        # aus einer eigenen Abfrage: die kostet eine Sekunde und die Zahl aendert
        # sich in dieser Zeitspanne nicht.
        laufend = {a.session_id for a in self._bestand.agenten if a.session_id}
        ergebnis = lade_statistik(
            Path.home() / ".claude" / "projects",
            bus.auftraege,
            laufende=laufend,
        )
        self.call_from_thread(self._statistik_uebernehmen, ergebnis)

    def _statistik_uebernehmen(self, ergebnis: Statistik) -> None:
        self._statistik = ergebnis
        self.query_one("#statistik", StatistikDashboard).setze_statistik(ergebnis)
        self._schreibe_log(
            t(
                "log.stats_loaded",
                anfragen=ergebnis.anfragen_gesamt,
                sekunden=f"{ergebnis.dauer_s:.1f}",
            )
        )

    def action_show_stats(self) -> None:
        """Zeigt den Statistik-Tab und rechnet neu."""
        self.query_one("#bereiche", TabbedContent).active = "tab-statistik"
        self.query_one("#statistik", StatistikDashboard).setze_laeuft(True)
        self.statistik_laden()

    @work(thread=True, group="namen")
    def namen_laden(self) -> None:
        """Holt den Namenspool.

        Bewusst NICHT im Sekundentakt: der Pool aendert sich nur, wenn ein
        Agent startet oder endet - ein Unterprozess je Aktualisierung waere
        reine Verschwendung.
        """
        pool = self._quelle.namen()
        self.call_from_thread(self._namen_uebernehmen, pool)

    def _namen_uebernehmen(self, pool: Namenspool) -> None:
        self._reserviert = list(pool.reserviert)
        self.query_one("#kopf", KopfPanel).namen_setzen(pool.motiv, len(pool.frei))

    @work(thread=True, exclusive=True, group="verlauf")
    def verlauf_laden(self, agent: Agent) -> None:
        # Der Verlauf haengt an der SITZUNG, nicht am Namen. Bis zum 15.09.2026
        # ging hier nur der Name hinaus, und unter "Charlene" standen Auftraege
        # vom 31.07. an eine Sitzung, die es seit Wochen nicht mehr gab.
        seit = startzeit(self._bestand.zeit, agent.laufzeit_ms)
        auftraege = self._quelle.verlauf(agent.name, session_id=agent.session_id, seit=seit)
        self.call_from_thread(self._verlauf_zeigen, agent, auftraege)

    def _verlauf_zeigen(self, agent: Agent, auftraege: list[Any]) -> None:
        # Die Sperre prueft Name, Rechner UND Sitzung. Bis zum 09.08.2026 hiess
        # es hier nur "!= name", und beim Sprung von Petra@SENZA auf
        # Petra@RAINBOW blieb der Verlauf des einen neben der Zeile des anderen
        # stehen. Seit der Verlauf an der Sitzung haengt, gehoert sie dazu.
        gewaehlt = self._gewaehlt
        if (
            gewaehlt is None
            or gewaehlt.name != agent.name
            or gewaehlt.rechner != agent.rechner
            or gewaehlt.session_id != agent.session_id
        ):
            return  # Auswahl hat sich waehrenddessen geaendert
        titel = self.query_one("#agenten", AgentenTabelle).beschriftung(gewaehlt)
        self.query_one("#verlauf", VerlaufPanel).zeigen(titel, auftraege)

    # -- Ereignisse -----------------------------------------------------

    def on_agenten_tabelle_ausgewaehlt(self, ereignis: AgentenTabelle.Ausgewaehlt) -> None:
        self._gewaehlt = ereignis.agent
        try:
            eingabe = self.query_one("#eingabe", Input)
            knopf = self.query_one("#senden", Button)
        except NoMatches:
            # Beim Beenden kann eine Auswahl-Nachricht noch ankommen, wenn der
            # Bildschirm schon abgebaut ist - belegt in der CI (windows-latest,
            # Python 3.12) am 15.09.2026. Dann gibt es nichts mehr zu fuellen.
            return
        agent = ereignis.agent

        # An die eigene Sitzung wird nichts gesendet: der Auftrag laege im
        # Eingang genau der Sitzung, die ihn gerade abschickt. Der Verlauf
        # bleibt trotzdem sichtbar, er ist ja der eigene.
        gesperrt = agent is None or agent.selbst
        self.query_one("#eingabe-zeile", ClearableInput).set_disabled(gesperrt)
        knopf.disabled = gesperrt

        if agent is None:
            eingabe.placeholder = t("chat.placeholder_none")
            self.query_one("#verlauf", VerlaufPanel).leeren(t("chat.none_selected"))
        else:
            # Beschriftung statt blossem Namen: bei zwei gleichnamigen Agenten
            # steht hier "Petra@SENZA", sonst saehe das Feld fuer beide gleich
            # aus - und man wuesste beim Tippen nicht, wen man anschreibt.
            beschriftung = self.query_one("#agenten", AgentenTabelle).beschriftung(agent)
            eingabe.placeholder = (
                t("chat.placeholder_self")
                if agent.selbst
                else t("chat.placeholder", name=beschriftung)
            )
            self.verlauf_laden(agent)
        self.refresh_bindings()

    def on_button_pressed(self, ereignis: Button.Pressed) -> None:
        kennung = ereignis.button.id or ""
        if kennung == "senden":
            self._senden()
            return
        if kennung.startswith("quick-"):
            self._schnellbefehl(kennung.removeprefix("quick-"))

    def _schnellbefehl(self, schluessel: str) -> None:
        """Legt einen vorformulierten Text ins Eingabefeld."""
        eingabe = self.query_one("#eingabe", Input)
        if eingabe.disabled:
            self.notify(t("notify.select_agent"), severity="warning")
            return
        eingabe.value = t(f"quick.{schluessel}_text")
        self.set_focus(eingabe)

    # -- Tabelle: Doppelklick und Kontextmenue --------------------------

    def on_agenten_tabelle_aufgerufen(self, ereignis: AgentenTabelle.Aufgerufen) -> None:
        self._detail_zeigen(ereignis.agent)

    def _detail_zeigen(self, agent: Agent) -> None:
        from claude_sanctuary.tui.screens.detail_screen import DetailScreen

        self._menue_ziel = agent
        self.push_screen(DetailScreen(agent), callback=self._detail_geschlossen)

    def _detail_geschlossen(self, aktion: str | None) -> None:
        agent = self._menue_ziel
        if aktion is None or agent is None:
            return
        if aktion == "senden":
            self.set_focus(self.query_one("#eingabe", Input))
        elif aktion == "kopieren":
            self._angaben_kopieren(agent)

    def on_agenten_tabelle_menue_gewuenscht(self, ereignis: AgentenTabelle.MenueGewuenscht) -> None:
        from textual_widgets import ContextMenuItem, ContextMenuScreen

        agent = ereignis.agent
        self._menue_ziel = agent
        hier = agent.rechner.upper() == self._bestand.rechner.upper()
        eintraege = [
            ContextMenuItem("details", t("menu.details")),
            ContextMenuItem("senden", t("menu.send"), enabled=not agent.selbst),
            ContextMenuItem("report", t("menu.report"), enabled=not agent.selbst),
            ContextMenuItem.separator(),
            ContextMenuItem("kopiere_name", t("menu.copy_name")),
            ContextMenuItem("kopiere_id", t("menu.copy_id"), enabled=bool(agent.session_id)),
            ContextMenuItem(
                "ordner", _nur_hier(t("menu.open_dir"), hier), enabled=hier and bool(agent.cwd)
            ),
            ContextMenuItem("neu_laden", t("menu.reload")),
            ContextMenuItem.separator(),
            ContextMenuItem("bild", t("menu.screenshot")),
            ContextMenuItem("nur_host", t("menu.filter_host")),
            ContextMenuItem("update", t("menu.update")),
            ContextMenuItem.separator(),
            ContextMenuItem("neustart", t("menu.restart"), enabled=bool(agent.session_id)),
            ContextMenuItem("stop", _nur_hier(t("menu.stop"), hier), enabled=hier),
        ]
        self.push_screen(
            ContextMenuScreen(eintraege, at=ereignis.bei),
            callback=self._menue_gewaehlt,
        )

    def _menue_gewaehlt(self, auswahl: str | None) -> None:
        agent = self._menue_ziel
        if auswahl is None or agent is None:
            return
        if auswahl == "details":
            self._detail_zeigen(agent)
        elif auswahl == "senden":
            self.set_focus(self.query_one("#eingabe", Input))
        elif auswahl == "report":
            self._schnellbefehl("status")
        elif auswahl == "kopiere_name":
            self._in_zwischenablage(agent.name)
        elif auswahl == "kopiere_id":
            self._in_zwischenablage(agent.session_id)
        elif auswahl == "ordner":
            self._ordner_oeffnen(agent)
        elif auswahl == "neu_laden":
            self.verlauf_laden(agent)
        elif auswahl == "bild":
            self._bild_holen(agent.rechner)
        elif auswahl == "nur_host":
            self.query_one("#agenten", AgentenTabelle).setze_filter(agent.rechner)
        elif auswahl == "update":
            self._update_starten(agent.rechner)
        elif auswahl == "neustart":
            self.action_restart_agent()
        elif auswahl == "stop":
            self.action_stop_agent()

    def _in_zwischenablage(self, text: str) -> None:
        if not text:
            return
        self.copy_to_clipboard(text)
        self.notify(t("notify.copied"))

    # -- Verlauf: Kontextmenue ------------------------------------------

    def on_verlauf_panel_menue_gewuenscht(self, ereignis: VerlaufPanel.MenueGewuenscht) -> None:
        from textual_widgets import ContextMenuItem, ContextMenuScreen

        panel = self.query_one("#verlauf", VerlaufPanel)
        self._verlauf_blase = ereignis.blase
        hat_blase = ereignis.blase is not None
        hat_inhalt = bool(panel.sichtbarer_text())
        eintraege = [
            ContextMenuItem("blase_kopieren", t("menu.chat.copy_entry"), enabled=hat_blase),
            ContextMenuItem("auftrag_id", t("menu.chat.copy_id"), enabled=hat_blase),
            ContextMenuItem.separator(),
            ContextMenuItem("alles_kopieren", t("menu.chat.copy_all"), enabled=hat_inhalt),
            ContextMenuItem("speichern", t("menu.chat.save"), enabled=hat_inhalt),
            ContextMenuItem.separator(),
            ContextMenuItem("leeren", t("menu.chat.clear"), enabled=hat_inhalt),
            ContextMenuItem(
                "alles_zeigen", t("menu.chat.restore"), enabled=panel.etwas_ausgeblendet
            ),
        ]
        self.push_screen(
            ContextMenuScreen(eintraege, at=ereignis.position),
            callback=self._verlauf_menue_gewaehlt,
        )

    def _verlauf_menue_gewaehlt(self, auswahl: str | None) -> None:
        if auswahl is None:
            return
        panel = self.query_one("#verlauf", VerlaufPanel)
        blase = self._verlauf_blase
        if auswahl == "blase_kopieren" and blase is not None:
            self._in_zwischenablage(blase.klartext)
        elif auswahl == "auftrag_id" and blase is not None:
            self._in_zwischenablage(blase.auftrag_id)
        elif auswahl == "alles_kopieren":
            self._in_zwischenablage(panel.sichtbarer_text())
        elif auswahl == "speichern":
            self._verlauf_speichern(panel)
        elif auswahl == "leeren":
            panel.ansicht_leeren()
        elif auswahl == "alles_zeigen":
            panel.alles_zeigen()

    def _verlauf_speichern(self, panel: VerlaufPanel) -> None:
        """Fragt nach einem Ziel und schreibt den sichtbaren Verlauf dorthin."""
        from textual_fspicker import FileSave, Filters

        if not panel.sichtbarer_text():
            return
        self.push_screen(
            FileSave(
                location=self._letzter_speicherort,
                default_file=panel.vorschlagsname(),
                title=t("save.title"),
                save_button=t("save.button"),
                cancel_button=t("save.cancel"),
                filters=Filters(
                    (t("save.filter_text"), lambda p: p.suffix.lower() == ".txt"),
                    (t("save.filter_all"), lambda _p: True),
                ),
            ),
            callback=self._verlauf_datei_gewaehlt,
        )

    def _verlauf_datei_gewaehlt(self, ziel: Path | None) -> None:
        if ziel is None:
            return
        panel = self.query_one("#verlauf", VerlaufPanel)
        try:
            # newline="\n": sonst macht Windows CRLF daraus, und die Datei
            # sieht auf jedem anderen Rechner falsch aus.
            ziel.write_text(f"{panel.sichtbarer_text()}\n", encoding="utf-8", newline="\n")
        except OSError as fehler:
            # markup=False: der Pfad ist Fremdtext, eine eckige Klammer darin
            # wuerde rich als Auszeichnung lesen.
            self.notify(str(fehler), severity="error", markup=False)
            return
        self._letzter_speicherort = str(ziel.parent)
        self.notify(t("notify.saved", pfad=str(ziel)), markup=False)

    def _angaben_kopieren(self, agent: Agent) -> None:
        zeilen = [
            f"{agent.name} ({agent.rechner})",
            f"Status: {agent.status}",
            f"Modell: {agent.modell or '-'}   Claude: {agent.version or '-'}",
            f"System: {agent.system or '-'}",
            f"Ordner: {agent.cwd or '-'}",
            f"Kontext: {agent.kontext}   Tokens: {agent.tokens}",
            f"Sitzung: {agent.session_id or '-'}",
        ]
        self._in_zwischenablage("\n".join(zeilen))

    def _ordner_oeffnen(self, agent: Agent) -> None:
        if not agent.cwd:
            self.notify(t("notify.no_dir"), severity="warning")
            return
        if agent.rechner.upper() != self._bestand.rechner.upper():
            self.notify(
                t("notify.remote_dir", name=agent.name, rechner=agent.rechner),
                severity="warning",
            )
            return
        # Nicht ueber den Link-Mixin: der kennt nur bereits registrierte
        # Ziele. Hier ist der Pfad direkt bekannt.
        with contextlib.suppress(Exception):
            oeffne_ordner(agent.cwd)

    def on_input_submitted(self, ereignis: Input.Submitted) -> None:
        if ereignis.input.id == "eingabe":
            self._senden()

    # -- Aktionen -------------------------------------------------------

    def _senden(self) -> None:
        if self._gewaehlt is None:
            self.notify(t("notify.select_agent"), severity="warning")
            return
        if self._gewaehlt.selbst:
            # Zweiter Riegel neben dem gesperrten Feld - erreichbar bliebe
            # der Weg sonst ueber die Eingabetaste.
            self.notify(t("chat.placeholder_self"), severity="warning")
            return
        eingabe = self.query_one("#eingabe", Input)
        text = eingabe.value.strip()
        if not text:
            self.notify(t("notify.no_text"), severity="warning")
            return
        self._auftrag_ablegen(self._gewaehlt.name, text, self._gewaehlt.rechner)
        eingabe.value = ""

    @work(thread=True, group="senden")
    def _auftrag_ablegen(self, name: str, text: str, host: str) -> None:
        # Rechner UND Absender mitgeben: der Rechner spart dem Bus die
        # Mesh-Suche, der Absender ist noetig, weil diese Oberflaeche keine
        # Claude-Sitzung ist - ohne ihn stand in jedem Auftrag "unbekannt".
        fehler = self._quelle.senden(name, text, quittung=True, host=host, von=ABSENDER)
        self.call_from_thread(self._senden_fertig, name, fehler)

    def _senden_fertig(self, name: str, fehler: str) -> None:
        if fehler:
            self._schreibe_log(t("log.send_failed", name=name, fehler=fehler), "error")
            self.notify(fehler, severity="error", markup=False)
            return
        self._schreibe_log(t("log.sent", name=name), "success")
        # Den Agenten laden, nicht seinen Namen: der Verlauf haengt an der
        # Sitzung. Hier stand bis zum 16.09.2026 der Name, und der Worker
        # starb mit AttributeError, sobald ein Auftrag abgelegt war.
        if self._gewaehlt is not None:
            self.verlauf_laden(self._gewaehlt)
        self.aktualisieren()

    # -- Bildschirmfoto -------------------------------------------------

    def action_bildschirmfoto(self) -> None:
        """Nimmt den Bildschirm auf - vom gewaehlten Agenten, sonst von hier.

        Ohne Auswahl ist der eigene Rechner das Naheliegende: das Bild soll
        zeigen, was gerade zu sehen ist, und nicht nichts.
        """
        agent = self._gewaehlt
        rechner = agent.rechner if agent is not None else self._bestand.rechner
        if not rechner:
            # Vor der ersten Abfrage ist noch kein Rechnername bekannt.
            self.notify(t("notify.no_host"), severity="warning")
            return
        self._bild_holen(rechner)

    def _bild_holen(self, rechner: str) -> None:
        """Stoesst die Aufnahme an. Der eigene Rechner braucht kein Ziel."""
        eigener = rechner.upper() == self._bestand.rechner.upper()
        self.notify(t("notify.shot_running", rechner=rechner))
        self._bild_aufnehmen("" if eigener else rechner, rechner)

    @work(thread=True, exclusive=True, group="bild")
    def _bild_aufnehmen(self, ziel: str, anzeige: str) -> None:
        pfad, fehler = self._quelle.bildschirmfoto(ziel)
        self.call_from_thread(self._bild_fertig, pfad, fehler, anzeige)

    def _bild_fertig(self, pfad: str, fehler: str, rechner: str) -> None:
        if fehler or not pfad:
            self._schreibe_log(t("log.shot_failed", rechner=rechner, fehler=fehler), "error")
            self.notify(
                fehler or t("log.shot_failed", rechner=rechner, fehler="-"), severity="error"
            )
            return
        from claude_sanctuary.tui.screens.bild_screen import BildScreen

        self._bild_rechner = rechner
        self._bild_pfad = pfad
        self.push_screen(BildScreen(pfad, rechner), callback=self._bild_geschlossen)

    def _bild_geschlossen(self, aktion: str | None) -> None:
        if aktion == "neu":
            self._bild_holen(self._bild_rechner)
        elif aktion == "kopieren":
            self._in_zwischenablage(self._bild_pfad)

    # -- Rundruf --------------------------------------------------------

    def action_broadcast(self) -> None:
        """Oeffnet den Dialog fuer eine Nachricht an alle Agenten."""
        from claude_sanctuary.tui.screens.rundruf_screen import RundrufScreen

        if not [a for a in self._bestand.agenten if not a.selbst]:
            self.notify(t("broadcast.nobody"), severity="warning")
            return
        self.push_screen(
            RundrufScreen(self._bestand.agenten, self._reserviert),
            callback=self._rundruf_abgeschickt,
        )

    def _rundruf_abgeschickt(self, ergebnis: Any | None) -> None:
        if ergebnis is None:
            return
        ziele = [(a.name, a.rechner) for a in ergebnis.empfaenger]
        self.notify(t("broadcast.running", anzahl=len(ziele)))
        self._rundruf_senden(ergebnis.text, ziele)

    @work(thread=True, group="rundruf")
    def _rundruf_senden(self, text: str, ziele: list[tuple[str, str]]) -> None:
        """Schickt je Agent einen eigenen Auftrag.

        Nacheinander und nicht als ein Rundruf: der Rundruf des Bus bleibt
        bewusst auf dem eigenen Rechner, damit waeren alle anderen aussen vor.
        Je Agent ein Auftrag heisst ausserdem: eigene Kennung, eigener
        Eintrag im Verlauf, eigene Quittung.
        """
        fehler: list[str] = []
        for name, rechner in ziele:
            meldung = self._quelle.senden(name, text, quittung=True, host=rechner, von=ABSENDER)
            if meldung:
                fehler.append(f"{name}@{rechner.upper()}: {meldung}")
        self.call_from_thread(self._rundruf_fertig, len(ziele), fehler)

    def _rundruf_fertig(self, anzahl: int, fehler: list[str]) -> None:
        geglueckt = anzahl - len(fehler)
        self._schreibe_log(t("log.broadcast", anzahl=geglueckt, gesamt=anzahl), "success")
        for meldung in fehler:
            self._schreibe_log(t("log.send_failed", name="", fehler=meldung), "error")
        if fehler:
            self.notify(t("broadcast.partly", anzahl=geglueckt, gesamt=anzahl), severity="warning")
        self.aktualisieren()
        if self._gewaehlt is not None:
            self.verlauf_laden(self._gewaehlt)

    # -- Neustart -------------------------------------------------------

    def action_restart_agent(self) -> None:
        """Beendet den gewaehlten Agenten und setzt ihn sofort fort.

        Zweck ist der Versionswechsel: eine laufende Sitzung haelt ihre
        Claude-Version fest, ein Neustart holt die installierte. Mit
        ``--resume`` bleibt dabei das Gespraech erhalten, und weil die
        Sitzungskennung dieselbe bleibt, auch der Name.
        """
        from claude_sanctuary.tui.screens.bestaetigung_screen import BestaetigungScreen

        agent = self._gewaehlt
        if agent is None:
            self.notify(t("notify.select_agent"), severity="warning")
            return
        # Seit dem 14.08.2026 geht der Neustart auch ueber Rechnergrenzen: das
        # CLI des Zielrechners beendet die Sitzung und oeffnet das Fenster
        # dort. Von hier aus ginge beides nicht - "sanctuary stop" kennt kein
        # Ziel, und ein Fenster braucht den Desktop des anderen Rechners.
        if not agent.session_id:
            self.notify(t("notify.no_session"), severity="warning")
            return

        self._neustart_kandidat = agent
        self.push_screen(
            BestaetigungScreen(
                titel=t("confirm.restart_title"),
                text=t("confirm.restart_text", name=agent.name),
            ),
            callback=self._neustart_bestaetigt,
        )

    def _neustart_bestaetigt(self, ja: bool | None) -> None:
        agent = self._neustart_kandidat
        self._neustart_kandidat = None
        if ja and agent is not None:
            self._neustart_ausfuehren(agent.name, agent.session_id, agent.cwd, agent.rechner)

    @work(thread=True, group="neustart")
    def _neustart_ausfuehren(self, name: str, session_id: str, cwd: str, rechner: str = "") -> None:
        from claude_sanctuary.tui.starter import starte_resume

        # Auf einem anderen Rechner macht das dortige CLI beides in einem Zug -
        # von hier aus laesst sich dort kein Fenster oeffnen.
        if rechner and rechner.upper() != self._bestand.rechner.upper():
            fehler = self._quelle.neustarten_fern(rechner, session_id, cwd)
            self.call_from_thread(self._neustart_fertig, name, fehler)
            return

        fehler = self._quelle.stoppen(name)
        if fehler:
            self.call_from_thread(self._neustart_fertig, name, fehler)
            return
        if not self._sitzung_verschwunden(session_id):
            self.call_from_thread(
                self._neustart_fertig, name, t("restart.still_running", name=name)
            )
            return
        fehler = starte_resume(session_id, cwd, self._einstellungen.laden())
        self.call_from_thread(self._neustart_fertig, name, fehler)

    STERBEFRIST = 8.0
    """Wie lange nach dem Stop auf das Verschwinden der Sitzung gewartet wird."""

    def _sitzung_verschwunden(self, session_id: str) -> bool:
        """Wartet, bis die Sitzung wirklich aus der Liste ist.

        Hier stand ein festes ``time.sleep(1.5)``, und das war geraten. Wer
        das Fenster oeffnet, waehrend der alte Prozess noch lebt, bekommt ZWEI
        Prozesse auf einem Transkript - beide unter derselben Sitzungskennung
        und damit unter demselben Namen. Am 16.08.2026 auf senza genau so
        passiert (PID 1319787 und 3585570), dort ueber den fernen Weg, der
        gar nicht beendete. Der lokale Weg hatte dasselbe Loch, nur schmaler.

        Gefragt wird die Quelle, nicht die PID. Eine Nummer kann nach dem
        Ausstieg laengst neu vergeben sein, und ueber Rechnergrenzen hat die
        Oberflaeche ohnehin keinen Zugriff darauf. Wahr ist, was die
        Instanzliste sagt: solange die Sitzung dort steht, wird sie gefuehrt.
        """
        ende = time.monotonic() + self.STERBEFRIST
        while True:
            agenten = self._quelle.bestand().agenten
            if not any(a.session_id == session_id for a in agenten):
                return True
            if time.monotonic() >= ende:
                return False
            time.sleep(0.25)

    def _neustart_fertig(self, name: str, fehler: str) -> None:
        if fehler:
            self._schreibe_log(t("log.restart_failed", name=name, fehler=fehler), "error")
            self.notify(fehler, severity="error", markup=False)
        else:
            self._schreibe_log(t("log.restarted", name=name), "success")
        self.set_timer(3.0, self.aktualisieren)
        self.set_timer(3.5, self.namen_laden)

    # -- Claude aktualisieren -------------------------------------------

    def _update_starten(self, rechner: str) -> None:
        """Aktualisiert Claude Code auf einem Rechner."""
        eigener = rechner.upper() == self._bestand.rechner.upper()
        verfahren = str(self._einstellungen.laden().get("update_verfahren", "claude"))
        self.notify(t("notify.update_running", rechner=rechner))
        self._schreibe_log(t("log.update_started", rechner=rechner, verfahren=verfahren))
        self._update_ausfuehren("" if eigener else rechner, rechner, verfahren)

    @work(thread=True, exclusive=True, group="update")
    def _update_ausfuehren(self, ziel: str, anzeige: str, verfahren: str) -> None:
        version, fehler = self._quelle.aktualisiere_claude(ziel, verfahren)
        self.call_from_thread(self._update_fertig, anzeige, version, fehler)

    def _update_fertig(self, rechner: str, version: str, fehler: str) -> None:
        if fehler:
            self._schreibe_log(t("log.update_failed", rechner=rechner, fehler=fehler), "error")
            self.notify(fehler, severity="error", markup=False)
            return
        self._schreibe_log(t("log.updated", rechner=rechner, version=version or "?"), "success")
        self.notify(t("notify.updated", rechner=rechner, version=version or "?"))
        self.aktualisieren()

    def action_refresh(self) -> None:
        self.aktualisieren()

    def action_show_usage(self) -> None:
        """Ermittelt den Verbrauch - einmalig, auf Zuruf.

        Bewusst kein Dauerzustand und keine Einstellung: der Operator liest
        dafuer jedes Transkript vollstaendig. Im Fuenf-Sekunden-Takt waere das
        Verschwendung, als einmalige Abfrage ist es die Wartezeit wert.
        """
        self.notify(t("notify.usage_running"))
        self.aktualisieren(tokens=True)

    def action_focus_filter(self) -> None:
        with contextlib.suppress(Exception):
            self.set_focus(self.query_one("#agenten-filter", Input))

    def action_toggle_local(self) -> None:
        self._nur_lokal = not self._nur_lokal
        self._einstellungen.speichern({"nur_lokal": self._nur_lokal})
        self._schreibe_log(t("log.local_on") if self._nur_lokal else t("log.local_off"))
        self.aktualisieren()

    def action_toggle_log(self) -> None:
        panel = self.query_one("#log", LogPanel)
        splitter = self.query_one("#log-splitter", HorizontalSplitter)
        panel.toggle()
        splitter.display = panel.display
        self._einstellungen.speichern({"log_sichtbar": panel.display})

    def action_cycle_theme(self) -> None:
        namen = sorted(self.available_themes.keys())
        if not namen:
            return
        try:
            index = namen.index(self.theme)
        except ValueError:
            index = -1
        naechstes = namen[(index + 1) % len(namen)]
        self.theme = naechstes
        self.notify(t("notify.theme", name=THEME_DISPLAY_NAMES.get(naechstes, naechstes)))

    def watch_theme(self, theme_name: str) -> None:
        """Persistiert jede Theme-Aenderung, auch die aus der Befehlspalette."""
        if not hasattr(self, "_einstellungen"):
            return
        with contextlib.suppress(Exception):
            if self._einstellungen.laden().get("theme") != theme_name:
                self._einstellungen.speichern({"theme": theme_name})
        self._theme_melden()

    def _theme_melden(self) -> None:
        """Schreibt das aktive Theme ins Protokoll.

        Textual zeigt nirgends an, welches Theme gerade laeuft - nach einem
        Neustart weiss man also nicht, was man vor sich hat. Der technische
        Name steht mit dabei, weil genau der in den Einstellungen und in der
        Befehlspalette auftaucht.
        """
        with contextlib.suppress(Exception):
            from textual_themes import THEME_DISPLAY_NAMES

            name = self.theme or ""
            anzeige = THEME_DISPLAY_NAMES.get(name, name)
            beschriftung = f"{anzeige} ({name})" if anzeige != name else name
            self._schreibe_log(t("log.theme_aktiv", name=beschriftung))

    async def action_quit(self) -> None:
        """Beendet die Oberflaeche - im Browser nicht.

        Im Browser beendete ``q`` die ganze Sitzung, und danach blieb nur
        Neuladen (Michaels Test am 15.09.2026). Das Schliessen des Tabs raeumt
        trotzdem ab: textual-serve schickt dann ``ExitApp``, und das laeuft an
        dieser Aktion vorbei.
        """
        if self.is_web:
            self.notify(t("notify.web_quit"))
            return
        await super().action_quit()

    def action_show_about(self) -> None:
        self.push_screen(
            AboutScreen(
                app_name="claude-sanctuary",
                version=__version__,
                author=__author__,
                release=__year__,
                description=t("about.description"),
                license="Apache-2.0",
                lang=current_language(),
                url="https://github.com/michaelblaess/claude-sanctuary",
            )
        )

    def action_show_help(self) -> None:
        from claude_sanctuary.tui.screens.hilfe_screen import HilfeScreen

        self.push_screen(HilfeScreen(self._keymap_ergebnis, self._keymap_stil, self._keymap_vim))

    def action_show_details(self) -> None:
        # Dasselbe wie Doppelklick und Kontextmenue, jetzt auch ueber d bzw. F6.
        if self._gewaehlt is not None:
            self._detail_zeigen(self._gewaehlt)

    def action_show_settings(self) -> None:
        from claude_sanctuary.tui.screens.einstellungen_screen import EinstellungenScreen

        self.push_screen(
            EinstellungenScreen(self._einstellungen.laden(), lang=current_language()),
            callback=self._einstellungen_geschlossen,
        )

    def _einstellungen_geschlossen(self, werte: dict[str, Any] | None) -> None:
        if werte is None:
            return
        self._einstellungen.speichern(werte)
        gespeichert = self._einstellungen.laden()
        if (
            dict(keymap.resolve(gespeichert).bindings) != dict(self._keymap_ergebnis.bindings)
            or keymap.vim_from_settings(gespeichert) != self._keymap_vim
        ):
            # Die Tasten werden beim Start gebunden - die neue Belegung gilt
            # erst ab dem naechsten Start, und das soll man erfahren.
            self.notify(t("notify.keymap_restart"))
        self._nur_lokal = bool(werte.get("nur_lokal", self._nur_lokal))
        self.notify(t("notify.settings_saved"))
        self.aktualisieren()
        self.namen_laden()

    def action_stop_agent(self) -> None:
        agent = self._gewaehlt
        if agent is None:
            self.notify(t("notify.select_agent"), severity="warning")
            return
        if agent.rechner.upper() != self._bestand.rechner.upper():
            self.notify(
                t("notify.remote_stop", name=agent.name, rechner=agent.rechner),
                severity="warning",
            )
            return
        from claude_sanctuary.tui.screens.bestaetigung_screen import BestaetigungScreen

        self._stop_kandidat = agent.name
        self.push_screen(
            BestaetigungScreen(
                titel=t("confirm.stop_title"),
                text=t("confirm.stop_text", name=agent.name, rechner=agent.rechner),
            ),
            callback=self._stop_bestaetigt,
        )

    def _stop_bestaetigt(self, ja: bool | None) -> None:
        # Eigene Methode statt Lambda: der Worker gibt ein Worker-Objekt
        # zurueck, der Callback muss aber None liefern.
        if ja and self._stop_kandidat:
            self._stop_ausfuehren(self._stop_kandidat)
        self._stop_kandidat = ""

    @work(thread=True, group="stop")
    def _stop_ausfuehren(self, name: str) -> None:
        fehler = self._quelle.stoppen(name)
        self.call_from_thread(self._stop_fertig, name, fehler)

    def _stop_fertig(self, name: str, fehler: str) -> None:
        if fehler:
            self._schreibe_log(t("log.stop_failed", name=name, fehler=fehler), "error")
        else:
            self._schreibe_log(t("log.stopped", name=name), "success")
        self.aktualisieren()
        self.namen_laden()

    def action_start_agent(self) -> None:
        from claude_sanctuary.tui.starter import starte_lokal

        # Die Einstellungen mitgeben: dort steht, welches Terminal genommen
        # wird und was darin vor Claude laufen soll.
        fehler = starte_lokal(einstellungen=self._einstellungen.laden())
        if fehler:
            self._schreibe_log(t("log.start_failed", fehler=fehler), "error")
            self.notify(fehler, severity="error", markup=False)
            return
        self._schreibe_log(t("log.started_agent", name="-"), "success")
        terminal = finde(str(self._einstellungen.laden().get("terminal", "")))
        if terminal is not None and not terminal.fenster:
            # Ohne Fenster sieht man vom Start nichts - also sagen, wo er laeuft.
            self.notify(t("notify.agent_in_tmux"))
            self._schreibe_log(t("notify.agent_in_tmux"))
        self.set_timer(3.0, self.aktualisieren)
        self.set_timer(3.5, self.namen_laden)

    def _handle_exception(self, error: Exception) -> None:
        """Schreibt den Traceback auf Platte, bevor der Fehlerdialog laeuft.

        Der CrashGuard zeigt ihn nur im Dialog. Scheitert der beim Aufbau
        selbst, waere der Bericht verloren - und der naechste Absturz wieder
        so undiagnostizierbar wie der erste.
        """
        with contextlib.suppress(Exception):
            absturz.absturz(error)
        super()._handle_exception(error)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Modale Dialoge sollen die App-Tasten nicht durchreichen.
        if len(self.screen_stack) > 1:
            return None
        if action in {"stop_agent", "restart_agent", "show_details"} and self._gewaehlt is None:
            return None
        return True

    # -- Hilfsmittel ----------------------------------------------------

    def _schreibe_log(self, zeile: str, stufe: str = "info") -> None:
        # Das LogPanel schreibt mit markup=True und ruft Text.from_markup auf -
        # eine eckige Klammer aus einer Fehlerausgabe reisst also die App um.
        # Keiner der eigenen Log-Texte enthaelt Auszeichnungen, deshalb darf
        # hier die ganze Zeile entschaerft werden. Siehe schutz.py.
        with contextlib.suppress(Exception):
            self.query_one("#log", LogPanel).write_log(self.linkify_urls(klartext(zeile)), stufe)
