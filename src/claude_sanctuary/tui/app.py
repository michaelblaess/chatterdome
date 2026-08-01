"""Die Zentrale als Textual-Oberflaeche."""

from __future__ import annotations

import contextlib
import dataclasses
import time
from pathlib import Path
from typing import Any, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Static, TabbedContent, TabPane
from textual_themes import THEME_DISPLAY_NAMES, register_all
from textual_widgets import (
    DISCLAIMER_VERSION,
    AboutScreen,
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
from claude_sanctuary.kern.einstellungen import ZUSTIMMUNG, Einstellungen
from claude_sanctuary.kern.lokale_quelle import LokaleQuelle
from claude_sanctuary.kern.modelle import Agent, Bestand, Namenspool
from claude_sanctuary.kern.protokolle import Quelle
from claude_sanctuary.tui.starter import oeffne_ordner
from claude_sanctuary.tui.widgets.agenten_tabelle import AgentenTabelle
from claude_sanctuary.tui.widgets.kopf_panel import KopfPanel
from claude_sanctuary.tui.widgets.status_zeile import StatusZeile
from claude_sanctuary.tui.widgets.verlauf_panel import VerlaufPanel

SCHNELLBEFEHLE = ("compact", "status", "pause", "done")
"""Vorformulierte Auftragstexte.

Sie fuellen NUR das Eingabefeld - abgeschickt wird weiter bewusst. Und sie
sind Text, keine Fernsteuerung: ein "/compact" kann der Agent nur selbst
ausloesen, der Auftrag bittet ihn darum.
"""


def _bus_datei() -> Path:
    """Pfad der Bus-Datenbank dieses Rechners."""
    import platform

    rechner = platform.node().upper() or "UNBEKANNT"
    return Path.home() / ".claude" / "bus" / rechner / "bus.db"


class SanctuaryApp(CrashGuard, ClickableLinksMixin, LogRouter, App[None]):  # type: ignore[misc]
    """Beobachtet die laufenden Sitzungen und verteilt Auftraege."""

    CSS_PATH = "app.tcss"
    TITLE = "Claude Sanctuary"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q,Q", "quit", "quit", key_display="q"),
        Binding("f5", "refresh_now", "refresh"),
        Binding("s,S", "show_settings", "settings", key_display="s"),
        Binding("l,L", "toggle_log", "log", key_display="l"),
        Binding("t,T", "cycle_theme", "theme", key_display="t"),
        Binding("i,I", "show_about", "about", key_display="i"),
        Binding("h,H", "show_help", "help", key_display="h"),
        Binding("n,N", "start_agent", "start", key_display="n"),
        Binding("delete", "stop_agent", "stop", key_display="DEL"),
        Binding("o,O", "toggle_local", "local", key_display="o"),
        Binding("slash", "focus_filter", "filter", key_display="/", show=False),
    ]

    _BINDING_I18N: ClassVar[dict[str, str]] = {
        "quit": "quit",
        "refresh_now": "refresh",
        "show_settings": "settings",
        "toggle_log": "log",
        "cycle_theme": "theme",
        "show_about": "about",
        "show_help": "help",
        "start_agent": "start",
        "stop_agent": "stop",
        "toggle_local": "local",
        "focus_filter": "filter",
    }

    def __init__(self, quelle: Quelle | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        register_all(self)
        self._einstellungen = Einstellungen()
        werte = self._einstellungen.laden()
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
        self._letzte_fehler: list[str] = []
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
                    yield HorizontalSplitter(
                        target_id="verlauf", min_size=5, id="eingabe-splitter"
                    )
                    with Vertical(id="eingabe-raum"):
                        yield Input(placeholder=t("chat.placeholder_none"), id="eingabe")
                        with Horizontal(id="schnellbefehle"):
                            yield Button(t("chat.send"), variant="primary", id="senden")
                            for schluessel in SCHNELLBEFEHLE:
                                yield Button(
                                    t(f"quick.{schluessel}"),
                                    variant="default",
                                    id=f"quick-{schluessel}",
                                    classes="schnell",
                                )
            with TabPane(t("tab.bus"), id="tab-bus"):
                yield Static(t("tab.empty"), classes="platzhalter")
            with TabPane(t("tab.stats"), id="tab-statistik"):
                yield Static(t("tab.empty"), classes="platzhalter")
        yield StatusZeile(id="status")
        yield HorizontalSplitter(target_id="bereiche", min_size=8, id="log-splitter")
        yield LogPanel(lang=current_language(), export_name="claude-sanctuary", id="log")
        yield Footer()

    def on_mount(self) -> None:
        self._binding_texte()
        self._schreibe_log(t("log.started", version=__version__))
        self.set_interval(self._takt, self._takt_abfrage)
        self.aktualisieren()
        self.namen_laden()
        self._frage_disclaimer()

    def _binding_texte(self) -> None:
        """Setzt Beschriftung und Tooltip der Bindings zur Laufzeit."""
        for taste, liste in self._bindings.key_to_bindings.items():
            for i, binding in enumerate(liste):
                schluessel = self._BINDING_I18N.get(binding.action)
                if schluessel is None:
                    continue
                self._bindings.key_to_bindings[taste][i] = dataclasses.replace(
                    binding,
                    description=t(f"binding.{schluessel}"),
                    tooltip=t(f"tooltip.{schluessel}"),
                )

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
    def aktualisieren(self) -> None:
        """Holt den Bestand. Laeuft im Thread, weil der Unterprozess blockiert."""
        self._laeuft = True
        try:
            bestand = self._quelle.bestand(mesh=not self._nur_lokal)
        finally:
            self._laeuft = False
        self.call_from_thread(self._bestand_uebernehmen, bestand)

    def _bestand_uebernehmen(self, bestand: Bestand) -> None:
        self._bestand = bestand
        laufzeit = int((time.monotonic() - self._start) * 1000)
        self.query_one("#kopf", KopfPanel).uebernehmen(
            bestand, nur_lokal=self._nur_lokal, laufzeit_ms=laufzeit
        )
        self.query_one("#agenten", AgentenTabelle).uebernehmen(bestand.agenten)
        self.query_one("#status", StatusZeile).uebernehmen(bestand)

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
        self.query_one("#kopf", KopfPanel).namen_setzen(pool.motiv, len(pool.frei))

    @work(thread=True, exclusive=True, group="verlauf")
    def verlauf_laden(self, name: str) -> None:
        auftraege = self._quelle.verlauf(name)
        self.call_from_thread(self._verlauf_zeigen, name, auftraege)

    def _verlauf_zeigen(self, name: str, auftraege: list[Any]) -> None:
        if self._gewaehlt is None or self._gewaehlt.name != name:
            return  # Auswahl hat sich waehrenddessen geaendert
        self.query_one("#verlauf", VerlaufPanel).zeigen(name, auftraege)

    # -- Ereignisse -----------------------------------------------------

    def on_agenten_tabelle_ausgewaehlt(self, ereignis: AgentenTabelle.Ausgewaehlt) -> None:
        self._gewaehlt = ereignis.agent
        eingabe = self.query_one("#eingabe", Input)
        knopf = self.query_one("#senden", Button)
        agent = ereignis.agent

        # An die eigene Sitzung wird nichts gesendet: der Auftrag laege im
        # Eingang genau der Sitzung, die ihn gerade abschickt. Der Verlauf
        # bleibt trotzdem sichtbar, er ist ja der eigene.
        gesperrt = agent is None or agent.selbst
        eingabe.disabled = gesperrt
        knopf.disabled = gesperrt

        if agent is None:
            eingabe.placeholder = t("chat.placeholder_none")
            self.query_one("#verlauf", VerlaufPanel).leeren(t("chat.none_selected"))
        else:
            eingabe.placeholder = (
                t("chat.placeholder_self") if agent.selbst
                else t("chat.placeholder", name=agent.name)
            )
            self.verlauf_laden(agent.name)
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

    def on_agenten_tabelle_menue_gewuenscht(
        self, ereignis: AgentenTabelle.MenueGewuenscht
    ) -> None:
        from textual_widgets import ContextMenuItem, ContextMenuScreen

        agent = ereignis.agent
        self._menue_ziel = agent
        hier = agent.rechner.upper() == self._bestand.rechner.upper()
        eintraege = [
            ContextMenuItem("details", t("menu.details")),
            ContextMenuItem("senden", t("menu.send"), enabled=not agent.selbst),
            ContextMenuItem("compact", t("menu.compact"), enabled=not agent.selbst),
            ContextMenuItem("report", t("menu.report"), enabled=not agent.selbst),
            ContextMenuItem.separator(),
            ContextMenuItem("kopiere_name", t("menu.copy_name")),
            ContextMenuItem("kopiere_id", t("menu.copy_id"), enabled=bool(agent.session_id)),
            ContextMenuItem("ordner", t("menu.open_dir"), enabled=hier and bool(agent.cwd)),
            ContextMenuItem("neu_laden", t("menu.reload")),
            ContextMenuItem.separator(),
            ContextMenuItem("nur_host", t("menu.filter_host")),
            ContextMenuItem("stop", t("menu.stop"), enabled=hier),
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
        elif auswahl == "compact":
            self._schnellbefehl("compact")
        elif auswahl == "report":
            self._schnellbefehl("status")
        elif auswahl == "kopiere_name":
            self._in_zwischenablage(agent.name)
        elif auswahl == "kopiere_id":
            self._in_zwischenablage(agent.session_id)
        elif auswahl == "ordner":
            self._ordner_oeffnen(agent)
        elif auswahl == "neu_laden":
            self.verlauf_laden(agent.name)
        elif auswahl == "nur_host":
            self.query_one("#agenten", AgentenTabelle).setze_filter(agent.rechner)
        elif auswahl == "stop":
            self.action_stop_agent()

    def _in_zwischenablage(self, text: str) -> None:
        if not text:
            return
        self.copy_to_clipboard(text)
        self.notify(t("notify.copied"))

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
        self._auftrag_ablegen(self._gewaehlt.name, text)
        eingabe.value = ""

    @work(thread=True, group="senden")
    def _auftrag_ablegen(self, name: str, text: str) -> None:
        fehler = self._quelle.senden(name, text, quittung=True)
        self.call_from_thread(self._senden_fertig, name, fehler)

    def _senden_fertig(self, name: str, fehler: str) -> None:
        if fehler:
            self._schreibe_log(t("log.send_failed", name=name, fehler=fehler), "error")
            self.notify(fehler, severity="error")
            return
        self._schreibe_log(t("log.sent", name=name), "success")
        self.verlauf_laden(name)
        self.aktualisieren()

    def action_refresh_now(self) -> None:
        self.aktualisieren()

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

        self.push_screen(HilfeScreen())

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

        fehler = starte_lokal()
        if fehler:
            self._schreibe_log(t("log.start_failed", fehler=fehler), "error")
            self.notify(fehler, severity="error")
            return
        self._schreibe_log(t("log.started_agent", name="-"), "success")
        self.set_timer(3.0, self.aktualisieren)
        self.set_timer(3.5, self.namen_laden)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Modale Dialoge sollen die App-Tasten nicht durchreichen.
        if len(self.screen_stack) > 1:
            return None
        if action == "stop_agent" and self._gewaehlt is None:
            return None
        return True

    # -- Hilfsmittel ----------------------------------------------------

    def _schreibe_log(self, zeile: str, stufe: str = "info") -> None:
        with contextlib.suppress(Exception):
            self.query_one("#log", LogPanel).write_log(self.linkify_urls(zeile), stufe)
