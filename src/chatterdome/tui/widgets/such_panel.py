"""Volltextsuche ueber alle Transkripte.

Die Suche laeuft mit einer kurzen Verzoegerung nach dem Tippen, nicht auf Enter:
bei 1 bis 2 ms je Abfrage waere ein Tastendruck zum Bestaetigen reine Zeremonie.
Die Verzoegerung fasst schnelles Tippen zusammen, damit nicht jeder Buchstabe
eine eigene Abfrage ausloest.

Sortiert wird nach der Bewertung von FTS5, nicht nach Zeit - wer sucht, will den
besten Treffer sehen. Deshalb traegt die Trefferliste bewusst KEINE
Spaltensortierung: eine nach Datum sortierte Trefferliste waere eine andere
Frage als die gestellte.
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widgets import DataTable, Static
from textual_widgets import ClearableInput

from chatterdome.i18n import format_datetime, t
from chatterdome.kern.suche import Bilanz, Treffer

VERZOEGERUNG = 0.25
"""Sekunden zwischen letztem Tastendruck und Abfrage."""


class SuchPanel(Vertical):
    """Eingabefeld, Trefferliste und eine Fusszeile mit dem Indexstand."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "zurueck", "back", show=False),
    ]

    class TrefferGewaehlt(Message):
        """Ein Treffer wurde bestaetigt - die App soll die Sitzung zeigen."""

        def __init__(self, treffer: Treffer) -> None:
            super().__init__()
            self.treffer = treffer

    class SucheGeaendert(Message):
        """Die Eingabe hat sich geaendert und will beantwortet werden."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._treffer: list[Treffer] = []
        self._timer: Timer | None = None
        self._spalten: list[Any] = []

    def compose(self) -> ComposeResult:
        yield ClearableInput(
            placeholder=t("search.placeholder"),
            tooltip=t("search.clear"),
            input_id="such-eingabe",
            id="such-zeile",
        )
        yield DataTable(id="such-treffer", cursor_type="row", zebra_stripes=True)
        yield Static(t("search.hint_empty"), id="such-fuss", markup=True)

    def on_mount(self) -> None:
        tabelle = self.query_one("#such-treffer", DataTable)
        self._spalten = list(
            tabelle.add_columns(
                t("search.col.when"),
                t("search.col.agent"),
                t("search.col.role"),
                t("search.col.text"),
            )
        )

    # -- Eingabe ------------------------------------------------------------

    def on_input_changed(self, ereignis: Any) -> None:
        """Sammelt Tastendruecke und fragt erst nach kurzer Ruhe ab."""
        if self._timer is not None:
            self._timer.stop()
        text = str(ereignis.value)
        self._timer = self.set_timer(VERZOEGERUNG, lambda: self._ausloesen(text))

    def _ausloesen(self, text: str) -> None:
        self._timer = None
        self.post_message(self.SucheGeaendert(text))

    def fokussiere(self) -> None:
        """Setzt den Schreibcursor ins Suchfeld - der Hauptweg in diesen Reiter."""
        self.query_one("#such-eingabe").focus()

    def action_zurueck(self) -> None:
        """Aus dem Eingabefeld heraus zurueck in die Trefferliste.

        Ohne diesen Weg tippt jeder Buchstabe weiter ins Feld, und die
        Tastenkuerzel der Anwendung sind unerreichbar - das uebliche
        Eingabemodus-Problem.
        """
        if self._treffer:
            self.query_one("#such-treffer", DataTable).focus()

    # -- Ergebnisse ---------------------------------------------------------

    def zeige(self, treffer: list[Treffer], frage: str) -> None:
        tabelle = self.query_one("#such-treffer", DataTable)
        tabelle.clear()
        self._treffer = treffer
        for nummer, fund in enumerate(treffer):
            tabelle.add_row(
                Text(format_datetime(fund.ts.isoformat()) if fund.ts else "-", style="dim"),
                self._agentzelle(fund),
                Text(fund.rolle, style="dim"),
                # Der Ausschnitt traegt die [b]-Auszeichnung des Index.
                # from_markup nimmt die Umbruchregeln nicht entgegen, deshalb
                # werden sie danach gesetzt - sonst waechst die Zeile in die Hoehe,
                # statt am Spaltenrand zu enden.
                self._fundzelle(fund.ausschnitt),
                key=str(nummer),
            )
        fuss = self.query_one("#such-fuss", Static)
        if not frage.strip():
            fuss.update(t("search.hint_empty"))
        elif treffer:
            fuss.update(t("search.hits", n=len(treffer)))
        else:
            fuss.update(f"[dim]{t('search.no_hits')}[/]")

    def zeige_bestand(self, bilanz: Bilanz, dateien: int, stuecke: int) -> None:
        """Meldet den Indexstand, sobald der Aufbau durch ist."""
        self.query_one("#such-fuss", Static).update(
            t("search.index_ready", dateien=dateien, stuecke=stuecke, s=f"{bilanz.dauer_s:.1f}")
        )

    def zeige_aufbau(self, erledigt: int, gesamt: int) -> None:
        self.query_one("#such-fuss", Static).update(t("search.indexing", n=erledigt, gesamt=gesamt))

    def _fundzelle(self, ausschnitt: str) -> Text:
        zelle = Text.from_markup(ausschnitt)
        zelle.no_wrap = True
        zelle.overflow = "ellipsis"
        return zelle

    def _agentzelle(self, fund: Treffer) -> Text:
        if fund.subagent:
            return Text(f"{fund.agent} +", style="#f1c40f")
        return Text(fund.agent)

    def on_data_table_row_selected(self, ereignis: DataTable.RowSelected) -> None:
        if ereignis.row_key.value is None:
            return
        nummer = int(ereignis.row_key.value)
        if 0 <= nummer < len(self._treffer):
            self.post_message(self.TrefferGewaehlt(self._treffer[nummer]))
