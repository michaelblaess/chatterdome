"""Tabelle der Agenten mit Filterzeile, Ampel und Sortierung per Kopfklick."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable
from textual_widgets import SearchInputWithHistory

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.modelle import Agent, Ampel

# Feste Ampelfarben statt Theme-Variablen oder benannter ANSI-Farben: eine
# Ampel hat rot, gelb und gruen, und die muessen auf jedem Theme genau so
# aussehen. Die benannte Farbe "yellow" ist in vielen Terminal-Paletten ein
# Orange - damit wird aus der Ampel eine vierte Farbe, die es nicht gibt.
AMPEL_FARBE = {
    Ampel.FREI: "bold #2ecc71",
    Ampel.BESCHAEFTIGT: "bold #f1c40f",
    Ampel.WEG: "bold #e74c3c",
}


def _tokens(wert: int) -> str:
    if wert <= 0:
        return "-"
    return str(wert) if wert < 10_000 else f"{round(wert / 1000)}k"


def _dauer(ms: int) -> str:
    minuten = ms // 60_000
    if minuten < 60:
        return f"{minuten}m"
    return f"{minuten // 60}h {minuten % 60:02d}m"


def _ordner(pfad: str, breite: int = 28) -> str:
    """Kuerzt von links - das Ende eines Pfades ist das Aussagekraeftige."""
    if len(pfad) <= breite:
        return pfad
    return "..." + pfad[-(breite - 3) :]


class AgentenDaten(DataTable[Any]):
    """DataTable, die Doppel- und Rechtsklick als eigene Nachricht meldet.

    Der Rechtsklick MUSS hier abgefangen werden: Textuals ``_on_click``
    prueft die Maustaste nicht, verschiebt den Cursor und postet unter
    Umstaenden ``RowSelected``. ``event.stop()`` genuegt dafuer nicht - es
    unterbindet nur das Bubbling, nicht die Aufrufkette entlang der MRO.
    Dafuer ist ``prevent_default()`` da, und ein ``super()``-Aufruf darf
    NICHT dazu, weil Textual die Basis ohnehin selbst aufruft.
    """

    class RechtsKlick(Message):
        def __init__(self, tabelle: AgentenDaten, zeile: int, bei: tuple[int, int]) -> None:
            super().__init__()
            self.tabelle = tabelle
            self.zeile = zeile
            self.bei = bei

        @property
        def control(self) -> AgentenDaten:
            return self.tabelle

    class DoppelKlick(Message):
        def __init__(self, tabelle: AgentenDaten, zeile: int) -> None:
            super().__init__()
            self.tabelle = tabelle
            self.zeile = zeile

        @property
        def control(self) -> AgentenDaten:
            return self.tabelle

    async def _on_click(self, event: events.Click) -> None:
        zeile = event.style.meta.get("row", -1)
        if not isinstance(zeile, int) or zeile < 0:
            return  # Spaltenkopf traegt kein "row"

        if event.button == 3:
            event.prevent_default()
            event.stop()
            self.move_cursor(row=zeile)
            self.post_message(self.RechtsKlick(self, zeile, (event.screen_x, event.screen_y)))
            return

        # Linksklick: den Cursor setzt Textuals Basis-Handler selbst, hier
        # kommt nur der zweite Klick als eigene Nachricht dazu.
        if event.button == 1 and event.chain >= 2:
            self.post_message(self.DoppelKlick(self, zeile))


class AgentenTabelle(Vertical):
    """Filterzeile plus Tabelle. Meldet die Auswahl als Message."""

    class Ausgewaehlt(Message):
        """Ein Agent wurde markiert."""

        def __init__(self, agent: Agent | None) -> None:
            super().__init__()
            self.agent = agent

    class Aufgerufen(Message):
        """Doppelklick auf einen Agenten - Detailansicht gewuenscht."""

        def __init__(self, agent: Agent) -> None:
            super().__init__()
            self.agent = agent

    class MenueGewuenscht(Message):
        """Rechtsklick auf einen Agenten."""

        def __init__(self, agent: Agent, bei: tuple[int, int]) -> None:
            super().__init__()
            self.agent = agent
            self.bei = bei

    # Nur Spalten in diesem Verzeichnis sind sortierbar.
    _SORTIER: ClassVar[dict[int, Callable[[Agent], Any]]] = {
        1: lambda a: a.name.casefold(),
        2: lambda a: a.rechner.casefold(),
        3: lambda a: (a.modell or "").casefold(),
        4: lambda a: (a.version or "").casefold(),
        5: lambda a: a.cwd.casefold(),
        6: lambda a: a.laufzeit_ms,
        7: lambda a: a.kontext,
        8: lambda a: a.post,
        9: lambda a: a.tokens,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agenten: list[Agent] = []
        self._sichtbar: list[Agent] = []
        self._filter = ""
        self._sortiert_nach: int | None = 8  # Post - dort steht der Handlungsbedarf
        self._absteigend = True
        self._kopf: list[str] = []
        self._spalten: list[Any] = []

    def compose(self) -> ComposeResult:
        yield SearchInputWithHistory(
            placeholder=t("filter.placeholder"),
            icon="🔍",
            input_id="agenten-filter",
            dropdown_id="agenten-filter-verlauf",
            id="agenten-suche",
        )
        yield AgentenDaten(id="agenten-daten", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        tabelle = self.query_one("#agenten-daten", DataTable)
        self._kopf = [
            t("col.state"), t("col.name"), t("col.host"), t("col.model"),
            t("col.version"), t("col.dir"), t("col.uptime"), t("col.context"),
            t("col.post"), t("col.tokens"), t("col.tool"),
        ]
        self._spalten = list(tabelle.add_columns(*self._kopf))
        tabelle.fixed_columns = 1
        self._kopf_zeichnen()

    # -- Daten ----------------------------------------------------------

    def uebernehmen(self, agenten: list[Agent]) -> None:
        """Ersetzt den Bestand und baut die Tabelle neu."""
        vorher = self.markierter
        self._agenten = agenten
        self._neu_aufbauen(merke=vorher.name if vorher else "")

    def setze_filter(self, text: str) -> None:
        self._filter = text.strip().casefold()
        self._neu_aufbauen()

    @property
    def markierter(self) -> Agent | None:
        """Der Agent unter dem Cursor, oder None."""
        tabelle = self.query_one("#agenten-daten", DataTable)
        zeile = tabelle.cursor_row
        if 0 <= zeile < len(self._sichtbar):
            return self._sichtbar[zeile]
        return None

    # -- intern ---------------------------------------------------------

    def _passt(self, a: Agent) -> bool:
        if not self._filter:
            return True
        heuhaufen = f"{a.name} {a.rechner} {a.cwd} {a.modell or ''}".casefold()
        return self._filter in heuhaufen

    def _neu_aufbauen(self, merke: str = "") -> None:
        tabelle = self.query_one("#agenten-daten", DataTable)
        gemerkt = merke or (self.markierter.name if self.markierter else "")

        sichtbar = [a for a in self._agenten if self._passt(a)]
        if self._sortiert_nach is not None:
            schluessel = self._SORTIER.get(self._sortiert_nach)
            if schluessel is not None:
                # Zweitschluessel immer aufsteigend - zweimal sortieren statt
                # Tupel, sonst dreht reverse auch den Zweitschluessel um.
                sichtbar.sort(key=lambda a: a.name.casefold())
                sichtbar.sort(key=schluessel, reverse=self._absteigend)
        self._sichtbar = sichtbar

        tabelle.clear()
        for a in sichtbar:
            tabelle.add_row(*self._zeile(a), key=f"{a.rechner}/{a.name}")

        if gemerkt:
            for i, a in enumerate(sichtbar):
                if a.name == gemerkt:
                    tabelle.move_cursor(row=i)
                    break
        self.post_message(self.Ausgewaehlt(self.markierter))

    def _zeile(self, a: Agent) -> list[Text]:
        name = Text(a.name + (" *" if a.selbst else ""), style="bold" if a.selbst else "")
        kontext = Text(
            _tokens(a.kontext),
            style="bold red" if a.kontext_kritisch else ("yellow" if a.kontext_eng else "dim"),
            justify="right",
        )
        post = Text(
            str(a.post) if a.post else "-",
            style="bold" if a.post else "dim",
            justify="right",
        )
        laufzeit = Text(_dauer(a.laufzeit_ms) + ("+" if a.fortgesetzt else ""), justify="right")
        return [
            Text("●", style=AMPEL_FARBE[a.ampel]),
            name,
            Text(a.rechner, style="dim"),
            Text(a.modell or "-", style="" if a.modell else "dim"),
            Text(a.version or "-", style="dim"),
            Text(_ordner(a.cwd), style="dim"),
            laufzeit,
            kontext,
            post,
            Text(_tokens(a.tokens), justify="right", style="dim"),
            Text(a.letztes_tool or "-", style="dim"),
        ]

    def _kopf_zeichnen(self) -> None:
        """Setzt den Sortierpfeil und haelt die Spaltenbreite stabil."""
        tabelle = self.query_one("#agenten-daten", DataTable)
        pfeil = " ▼" if self._absteigend else " ▲"
        for i, schluessel in enumerate(self._spalten):
            # Zwei Leerzeichen Reserve, damit die Spalte beim Wechsel nicht springt.
            aktiv = i == self._sortiert_nach
            beschriftung = f"{self._kopf[i]}{pfeil}" if aktiv else f"{self._kopf[i]}  "
            spalte = tabelle.columns.get(schluessel)
            if spalte is not None:
                spalte.label = Text(beschriftung)
        tabelle.refresh()

    # -- Ereignisse -----------------------------------------------------

    def on_data_table_header_selected(self, ereignis: DataTable.HeaderSelected) -> None:
        try:
            index = self._spalten.index(ereignis.column_key)
        except ValueError:
            return
        if index not in self._SORTIER:
            return
        if index == self._sortiert_nach:
            self._absteigend = not self._absteigend
        else:
            self._sortiert_nach = index
            self._absteigend = False
        self._kopf_zeichnen()
        self._neu_aufbauen()

    def on_data_table_row_highlighted(self, _ereignis: DataTable.RowHighlighted) -> None:
        self.post_message(self.Ausgewaehlt(self.markierter))

    def on_agenten_daten_doppel_klick(self, ereignis: AgentenDaten.DoppelKlick) -> None:
        agent = self._bei_zeile(ereignis.zeile)
        if agent is not None:
            self.post_message(self.Aufgerufen(agent))

    def on_agenten_daten_rechts_klick(self, ereignis: AgentenDaten.RechtsKlick) -> None:
        agent = self._bei_zeile(ereignis.zeile)
        if agent is not None:
            self.post_message(self.MenueGewuenscht(agent, ereignis.bei))

    def _bei_zeile(self, zeile: int) -> Agent | None:
        return self._sichtbar[zeile] if 0 <= zeile < len(self._sichtbar) else None

    def on_search_input_with_history_changed(self, ereignis: Message) -> None:
        wert = getattr(ereignis, "value", None)
        if isinstance(wert, str):
            self.setze_filter(wert)
