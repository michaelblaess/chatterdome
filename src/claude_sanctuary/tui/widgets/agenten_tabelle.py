"""Tabelle der Agenten mit Filterzeile, Ampel und Sortierung per Kopfklick."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable
from textual_widgets import SearchInputWithHistory

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.modelle import Agent, Ampel

AMPEL_FARBE = {
    Ampel.FREI: "bold green",
    Ampel.BESCHAEFTIGT: "bold yellow",
    Ampel.WEG: "bold red",
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


class AgentenTabelle(Vertical):
    """Filterzeile plus Tabelle. Meldet die Auswahl als Message."""

    class Ausgewaehlt(Message):
        """Ein Agent wurde markiert."""

        def __init__(self, agent: Agent | None) -> None:
            super().__init__()
            self.agent = agent

    # Nur Spalten in diesem Verzeichnis sind sortierbar.
    _SORTIER: ClassVar[dict[int, Callable[[Agent], Any]]] = {
        1: lambda a: a.name.casefold(),
        2: lambda a: a.rechner.casefold(),
        3: lambda a: (a.modell or "").casefold(),
        4: lambda a: a.cwd.casefold(),
        5: lambda a: a.laufzeit_ms,
        6: lambda a: a.kontext,
        7: lambda a: a.post,
        8: lambda a: a.tokens,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agenten: list[Agent] = []
        self._sichtbar: list[Agent] = []
        self._filter = ""
        self._sortiert_nach: int | None = 7  # Post - dort steht der Handlungsbedarf
        self._absteigend = True
        self._kopf: list[str] = []
        self._spalten: list[Any] = []

    def compose(self) -> ComposeResult:
        yield SearchInputWithHistory(
            placeholder=t("filter.placeholder"),
            icon="/",
            input_id="agenten-filter",
            id="agenten-suche",
        )
        yield DataTable(id="agenten-daten", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        tabelle = self.query_one("#agenten-daten", DataTable)
        self._kopf = [
            t("col.state"), t("col.name"), t("col.host"), t("col.model"),
            t("col.dir"), t("col.uptime"), t("col.context"), t("col.post"),
            t("col.tokens"), t("col.tool"),
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

    def on_search_input_with_history_changed(self, ereignis: Message) -> None:
        wert = getattr(ereignis, "value", None)
        if isinstance(wert, str):
            self.setze_filter(wert)
