"""Tabelle der Busnachrichten mit Filterzeile, Suche und Sortierung per Kopfklick."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import DataTable, Select, Static
from textual_widgets import SearchInputWithHistory

from claude_sanctuary.i18n import format_datetime, t
from claude_sanctuary.kern.busansicht import BINDUNGSARTEN, ZEITRAEUME, ZUSTANDSGRUPPEN, filtere
from claude_sanctuary.kern.modelle import Auftrag

# Feste Farben wie bei der Agentenampel: die Aussage haengt an der Farbe und
# darf nicht mit dem Thema wandern.
ZUSTAND_FARBE = {
    "submitted": "bold #f1c40f",
    "working": "bold #3498db",
    "input_required": "bold #9b59b6",
    "completed": "bold #2ecc71",
    "failed": "bold #e74c3c",
    "cancelled": "bold #e67e22",
    "expired": "bold #95a5a6",
}

TEXT_BREITE = 44
"""Deckel fuer die Inhaltsspalte. Ohne ihn schiebt eine lange Nachricht alle
Kennzahlen aus dem Bild - der volle Text steht rechts in der Detailansicht."""


def _kuerzen(text: str, breite: int = TEXT_BREITE) -> str:
    einzeilig = " ".join(text.split())
    if len(einzeilig) <= breite:
        return einzeilig
    return einzeilig[: breite - 3].rstrip() + "..."


class BusTabelle(Vertical):
    """Filterzeile plus Tabelle. Meldet die Auswahl als Nachricht."""

    class Ausgewaehlt(Message):
        """Ein Auftrag wurde markiert, oder die Auswahl wurde aufgehoben."""

        def __init__(self, auftrag: Auftrag | None) -> None:
            super().__init__()
            self.auftrag = auftrag

    class FilterGeaendert(Message):
        """Der sichtbare Ausschnitt hat sich geaendert - fuer die Kennzahlen."""

        def __init__(self, sichtbar: list[Auftrag]) -> None:
            super().__init__()
            self.sichtbar = sichtbar

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "zur_uebersicht", "overview", show=False),
    ]

    _ZEIT, _VON, _AN, _BINDUNG, _THEMA, _ZUSTAND, _TEXT = range(7)

    _SORTIER: ClassVar[dict[int, Callable[[Auftrag], Any]]] = {
        _ZEIT: lambda a: a.erstellt,
        _VON: lambda a: a.von.casefold(),
        _AN: lambda a: a.an.casefold(),
        _BINDUNG: lambda a: a.bindung or "",
        _THEMA: lambda a: a.topic.casefold(),
        _ZUSTAND: lambda a: a.zustand,
    }
    """Die Inhaltsspalte ist freier Text - alphabetisch sortiert ordnet sie nichts."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._auftraege: list[Auftrag] = []
        self._sichtbar: list[Auftrag] = []
        self._suche = ""
        self._zeitraum = "alle"
        self._gruppe = "alle"
        self._bindung = "alle"
        # Neueste oben: die Frage beim Oeffnen lautet "was ist gerade passiert".
        self._sortiert_nach: int | None = self._ZEIT
        self._absteigend = True
        self._gewaehlt = ""
        """ID des BEWUSST gewaehlten Auftrags.

        Nicht aus dem Cursor ableitbar: der steht nach jedem Aufbau auf der
        ersten Zeile, ohne dass jemand etwas ausgewaehlt haette.
        """
        self._kopf: list[str] = []
        self._spalten: list[Any] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="bus-filter"):
            yield Select(
                [(t(f"bus.range.{k}"), k) for k in ZEITRAEUME],
                value="alle",
                allow_blank=False,
                id="bus-zeitraum",
            )
            yield Select(
                [(t(f"bus.group.{k}"), k) for k in ZUSTANDSGRUPPEN],
                value="alle",
                allow_blank=False,
                id="bus-zustand",
            )
            yield Select(
                [(t(f"bus.bind.{k}"), k) for k in BINDUNGSARTEN],
                value="alle",
                allow_blank=False,
                id="bus-bindung",
            )
        yield SearchInputWithHistory(
            placeholder=t("bus.search"),
            icon="🔍",
            input_id="bus-suche-feld",
            dropdown_id="bus-suche-verlauf",
            id="bus-suche",
        )
        yield DataTable(id="bus-daten", cursor_type="row", zebra_stripes=True)
        # Eine leere DataTable zeigt gar nichts - dann ist nicht erkennbar, ob
        # der Filter zu eng ist oder der Bus wirklich leer.
        yield Static(t("bus.none"), id="bus-leer")

    def on_mount(self) -> None:
        tabelle = self.query_one("#bus-daten", DataTable)
        self._kopf = [
            t("bus.col.time"),
            t("bus.col.from"),
            t("bus.col.to"),
            t("bus.col.binding"),
            t("bus.col.topic"),
            t("bus.col.state"),
            t("bus.col.text"),
        ]
        self._spalten = list(tabelle.add_columns(*self._kopf))
        tabelle.fixed_columns = 3
        self.query_one("#bus-leer", Static).display = False
        self._kopf_zeichnen()

    # -- Daten ----------------------------------------------------------

    def uebernehmen(self, auftraege: list[Auftrag]) -> None:
        """Ersetzt den Bestand und baut die Tabelle neu auf."""
        self._auftraege = auftraege
        self._neu_aufbauen()

    @property
    def markierte(self) -> Auftrag | None:
        zeile = self.query_one("#bus-daten", DataTable).cursor_row
        if 0 <= zeile < len(self._sichtbar):
            return self._sichtbar[zeile]
        return None

    # -- intern ---------------------------------------------------------

    def _neu_aufbauen(self) -> None:
        tabelle = self.query_one("#bus-daten", DataTable)
        gemerkt = self._gewaehlt

        sichtbar = filtere(
            self._auftraege,
            zeitraum=self._zeitraum,
            gruppe=self._gruppe,
            bindung=self._bindung,
            suche=self._suche,
        )
        if self._sortiert_nach is not None:
            schluessel = self._SORTIER.get(self._sortiert_nach)
            if schluessel is not None:
                # Zweitschluessel immer aufsteigend - zweimal sortieren statt
                # Tupel, sonst dreht das Umkehren auch den Zweitschluessel um.
                sichtbar.sort(key=lambda a: a.erstellt)
                sichtbar.sort(key=schluessel, reverse=self._absteigend)
        self._sichtbar = sichtbar

        tabelle.clear()
        for auftrag in sichtbar:
            tabelle.add_row(*self._zeile(auftrag), key=auftrag.auftrag_id)

        self.query_one("#bus-leer", Static).display = not sichtbar
        self.post_message(self.FilterGeaendert(sichtbar))

        if gemerkt:
            for i, auftrag in enumerate(sichtbar):
                if auftrag.auftrag_id == gemerkt:
                    tabelle.move_cursor(row=i)
                    self.post_message(self.Ausgewaehlt(auftrag))
                    return
            # Der gewaehlte Auftrag faellt aus dem Filter: Auswahl aufheben,
            # sonst zeigt die Detailansicht etwas, das links nicht mehr steht.
            self._gewaehlt = ""
        self.post_message(self.Ausgewaehlt(None))

    def _zeile(self, a: Auftrag) -> list[Text]:
        person = bool(a.an_session)
        # Altbestand von vor der Unterscheidung ehrlich als unbekannt zeigen,
        # nicht als Rolle - er ist beides nicht, er stammt aus der Zeit davor.
        if not a.bindung:
            bindung = Text("?", style="dim")
        elif person:
            bindung = Text(t("bus.bind.person"), style="dim")
        else:
            bindung = Text(t("bus.bind.rolle"), style="#f1c40f")
        return [
            Text(format_datetime(a.erstellt), style="dim"),
            Text(a.von or "?"),
            Text(a.an or "?"),
            bindung,
            Text(a.topic or "-", style="dim"),
            Text(
                t(f"state.{a.zustand}") if a.zustand else "?",
                style=ZUSTAND_FARBE.get(a.zustand, "dim"),
            ),
            Text(_kuerzen(a.text) if a.text else "-", style="" if a.text else "dim"),
        ]

    def _kopf_zeichnen(self) -> None:
        """Setzt den Sortierpfeil und haelt die Spaltenbreite stabil."""
        tabelle = self.query_one("#bus-daten", DataTable)
        pfeil = " ▼" if self._absteigend else " ▲"
        for i, schluessel in enumerate(self._spalten):
            # Zwei Zeichen Reserve, sonst springt die Spalte beim Wechsel.
            aktiv = i == self._sortiert_nach
            beschriftung = f"{self._kopf[i]}{pfeil}" if aktiv else f"{self._kopf[i]}  "
            spalte = tabelle.columns.get(schluessel)
            if spalte is not None:
                spalte.label = Text(beschriftung)
        tabelle.refresh()

    # -- Ereignisse -----------------------------------------------------

    def on_select_changed(self, ereignis: Select.Changed) -> None:
        wert = str(ereignis.value)
        if ereignis.select.id == "bus-zeitraum":
            self._zeitraum = wert
        elif ereignis.select.id == "bus-zustand":
            self._gruppe = wert
        elif ereignis.select.id == "bus-bindung":
            self._bindung = wert
        else:
            return
        self._neu_aufbauen()

    def on_search_input_with_history_changed(self, ereignis: Message) -> None:
        wert = getattr(ereignis, "value", None)
        if isinstance(wert, str):
            self._suche = wert
            self._neu_aufbauen()

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
            # Zeit zuerst absteigend (neueste oben), Text aufsteigend.
            self._absteigend = index == self._ZEIT
        self._kopf_zeichnen()
        self._neu_aufbauen()

    def on_data_table_row_highlighted(self, _ereignis: DataTable.RowHighlighted) -> None:
        # Nur melden, wenn der Anwender wirklich in der Tabelle steht. Beim
        # Befuellen setzt Textual den Cursor selbst auf die erste Zeile und
        # loest dieses Ereignis aus - ohne diese Bedingung stuende sofort ein
        # Auftrag rechts, und die Uebersicht bekaeme niemand zu sehen.
        if not self.query_one("#bus-daten", DataTable).has_focus:
            return
        gewaehlt = self.markierte
        self._gewaehlt = gewaehlt.auftrag_id if gewaehlt else ""
        self.post_message(self.Ausgewaehlt(gewaehlt))

    def action_zur_uebersicht(self) -> None:
        """Hebt die Auswahl auf, damit rechts wieder die Uebersicht steht."""
        self._gewaehlt = ""
        self.post_message(self.Ausgewaehlt(None))
