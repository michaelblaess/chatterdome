"""Tabelle der Gedaechtnisnotizen mit Filter und Sortierung per Kopfklick."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable, Static
from textual_widgets import SearchInputWithHistory, vim_navigation_bindings

from chatterdome.i18n import t
from chatterdome.kern.gedaechtnis import Notiz
from chatterdome.tui.schutz import klartext_oder_nichts

# Feste Farben statt Theme-Variablen, wie bei der Agentenampel: die Aussage
# haengt an der Farbe selbst und darf nicht mit dem Thema wandern.
ZUSTAND_FARBE = {
    "fehler": "bold #e74c3c",
    "hinweis": "bold #f1c40f",
    "gut": "bold #2ecc71",
}

BESCHREIBUNG_BREITE = 46
"""Deckel fuer die Beschreibung.

Ohne Deckel wird die Spalte so breit wie die laengste Beschreibung und
schiebt alle Kennzahlen aus dem Bild. Der volle Text haengt als Hinweis an
der Zelle und steht in der Detailansicht.
"""


def _kuerzen(text: str, breite: int = BESCHREIBUNG_BREITE) -> str:
    einzeilig = " ".join(text.split())
    if len(einzeilig) <= breite:
        return einzeilig
    return einzeilig[: breite - 3].rstrip() + "..."


def zustand(notiz: Notiz) -> str:
    """Bewertet eine Notiz fuer die Ampelspalte.

    Rot steht ausschliesslich fuer nachpruefbare Maengel. Gelb ist ein
    Hinweis, kein Fehler: eine Notiz, auf die niemand verweist, kann voellig
    in Ordnung sein. Ohne diese Trennung wuerde die Spalte 45 von 164 Notizen
    als fehlerhaft ausweisen, die es nicht sind.
    """
    if not notiz.im_index or notiz.tote_verweise or not notiz.typ:
        return "fehler"
    if notiz.isoliert:
        return "hinweis"
    return "gut"


class NotizenDaten(DataTable[Any]):
    """DataTable, die den vollen Inhalt gekuerzter Zellen als Hinweis zeigt."""

    def _on_mount(self, event: events.Mount) -> None:
        # Vim-Ebene am Widget, siehe AgentenDaten._on_mount.
        if not getattr(self.app, "vim_navigation", False):
            return
        for key, action in vim_navigation_bindings():
            self._bindings.bind(key, action, show=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.zell_hinweise: dict[tuple[int, int], str] = {}
        self.kopf_hinweise: dict[int, str] = {}
        """Spaltenindex auf die Erklaerung der Spalte.

        Der Spaltenkopf liegt auf Zeile -1 - anders sind Hinweise je Spalte in
        Textual nicht zu haben, ein Hinweis gehoert immer dem ganzen Widget.
        """

    def watch_hover_coordinate(self, old: Coordinate, value: Coordinate) -> None:
        # super() ist Pflicht, sonst bleibt die alte Hervorhebung stehen.
        super().watch_hover_coordinate(old, value)
        if value.row == -1:
            self.tooltip = self.kopf_hinweise.get(value.column)
            return
        # Beschreibung und Dateiname stammen aus fremden Notizen - siehe schutz.py.
        self.tooltip = klartext_oder_nichts(self.zell_hinweise.get((value.row, value.column)))


class NotizenTabelle(Vertical):
    """Filterzeile plus Tabelle. Meldet die Auswahl als Nachricht."""

    class Ausgewaehlt(Message):
        """Eine Notiz wurde markiert, oder die Auswahl wurde aufgehoben."""

        def __init__(self, notiz: Notiz | None) -> None:
            super().__init__()
            self.notiz = notiz

    BINDINGS: ClassVar[list[BindingType]] = [
        # Ohne Rueckweg bleibt der Anwender nach dem ersten Klick in der
        # Detailansicht gefangen und kommt an die Uebersicht nicht mehr heran.
        Binding("escape", "zur_uebersicht", "overview", show=False),
    ]

    _ZUSTAND, _ART, _NAME, _ZEILEN, _EIN, _AUS, _ABRUFE, _BESCHREIBUNG = range(8)

    _SORTIER: ClassVar[dict[int, Callable[[Notiz], Any]]] = {
        _ART: lambda n: n.typ,
        _NAME: lambda n: n.name.casefold(),
        _ZEILEN: lambda n: n.zeilen,
        _EIN: lambda n: len(n.eingehend),
        _AUS: lambda n: len(n.verweist_auf),
        _ABRUFE: lambda n: n.recalls,
    }
    """Die Zustandsspalte ist ein Symbol und die Beschreibung freier Text -
    beide alphabetisch zu sortieren ordnet nichts Sinnvolles."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._notizen: list[Notiz] = []
        self._sichtbar: list[Notiz] = []
        self._filter = ""
        # Groesste zuerst: die Frage beim Oeffnen lautet "was ist hier dick".
        self._sortiert_nach: int | None = self._ZEILEN
        self._absteigend = True
        self._gewaehlt = ""
        """Name der BEWUSST gewaehlten Notiz.

        Nicht aus dem Cursor ableitbar: der steht nach jedem Aufbau auf der
        ersten Zeile, ohne dass jemand etwas ausgewaehlt haette. Wer das
        verwechselt, zeigt rechts sofort eine Notiz und die Uebersicht nie.
        """
        self._kopf: list[str] = []
        self._spalten: list[Any] = []

    def compose(self) -> ComposeResult:
        yield SearchInputWithHistory(
            placeholder=t("mem.filter"),
            icon="🔍",
            input_id="notizen-filter",
            dropdown_id="notizen-filter-verlauf",
            id="notizen-suche",
        )
        yield NotizenDaten(id="notizen-daten", cursor_type="row", zebra_stripes=True)
        # Eine DataTable ohne Zeilen zeigt gar nichts - der Anwender sieht
        # nicht, ob sein Filter zu eng ist oder das Laden noch laeuft.
        yield Static(t("mem.none"), id="notizen-leer")

    def on_mount(self) -> None:
        tabelle = self.query_one("#notizen-daten", DataTable)
        self._kopf = [
            t("mem.col.state"),
            t("mem.col.type"),
            t("mem.col.name"),
            t("mem.col.lines"),
            t("mem.col.in"),
            t("mem.col.out"),
            t("mem.col.recalls"),
            t("mem.col.desc"),
        ]
        self._spalten = list(tabelle.add_columns(*self._kopf))
        # Ampel und Name bleiben beim Blaettern nach rechts stehen.
        tabelle.fixed_columns = 3
        self.query_one("#notizen-leer", Static).display = False
        if isinstance(tabelle, NotizenDaten):
            tabelle.kopf_hinweise = {
                self._EIN: t("mem.tip.in"),
                self._AUS: t("mem.tip.out"),
                self._ABRUFE: t("mem.tip.recalls"),
            }
        self._kopf_zeichnen()

    # -- Daten ----------------------------------------------------------

    def uebernehmen(self, notizen: list[Notiz]) -> None:
        """Ersetzt den Bestand und baut die Tabelle neu auf."""
        self._notizen = notizen
        self._neu_aufbauen()

    def setze_filter(self, text: str) -> None:
        self._filter = text.strip().casefold()
        self._neu_aufbauen()

    @property
    def markierte(self) -> Notiz | None:
        tabelle = self.query_one("#notizen-daten", DataTable)
        zeile = tabelle.cursor_row
        if 0 <= zeile < len(self._sichtbar):
            return self._sichtbar[zeile]
        return None

    # -- intern ---------------------------------------------------------

    def _passt(self, notiz: Notiz) -> bool:
        if not self._filter:
            return True
        heuhaufen = f"{notiz.name} {notiz.typ} {notiz.beschreibung} {notiz.index_text}".casefold()
        return self._filter in heuhaufen

    def _neu_aufbauen(self) -> None:
        tabelle = self.query_one("#notizen-daten", DataTable)
        gemerkt = self._gewaehlt

        sichtbar = [n for n in self._notizen if self._passt(n)]
        if self._sortiert_nach is not None:
            schluessel = self._SORTIER.get(self._sortiert_nach)
            if schluessel is not None:
                # Zweitschluessel immer aufsteigend - zweimal sortieren statt
                # Tupel, sonst dreht das Umkehren auch den Zweitschluessel um.
                sichtbar.sort(key=lambda n: n.name.casefold())
                sichtbar.sort(key=schluessel, reverse=self._absteigend)
        self._sichtbar = sichtbar

        tabelle.clear()
        hinweise: dict[tuple[int, int], str] = {}
        for zeile, notiz in enumerate(sichtbar):
            tabelle.add_row(*self._zeile(notiz), key=notiz.schluessel)
            if notiz.beschreibung and len(notiz.beschreibung) > BESCHREIBUNG_BREITE:
                hinweise[(zeile, self._BESCHREIBUNG)] = " ".join(notiz.beschreibung.split())
            hinweise[(zeile, self._NAME)] = notiz.datei.name
        if isinstance(tabelle, NotizenDaten):
            tabelle.zell_hinweise = hinweise

        # Ein leerer Static belegt trotz height:auto eine Zeile, also wird er
        # ein- und ausgeblendet statt geleert.
        self.query_one("#notizen-leer", Static).display = not sichtbar

        if gemerkt:
            for i, notiz in enumerate(sichtbar):
                if notiz.name == gemerkt:
                    tabelle.move_cursor(row=i)
                    break
            self.post_message(self.Ausgewaehlt(self.markierte))
        else:
            # Erster Aufbau: keine Auswahl, damit die Uebersicht stehen bleibt.
            self.post_message(self.Ausgewaehlt(None))

    def _zeile(self, notiz: Notiz) -> list[Text]:
        art = notiz.typ or "?"
        abrufe = Text(
            str(notiz.recalls) if notiz.recalls else "-",
            style="bold" if notiz.recalls else "dim",
            justify="right",
        )
        return [
            Text("●", style=ZUSTAND_FARBE[zustand(notiz)]),
            Text(art, style="" if notiz.typ else "dim"),
            Text(notiz.name),
            Text(str(notiz.zeilen), justify="right", style="dim"),
            Text(
                str(len(notiz.eingehend)) if notiz.eingehend else "-",
                justify="right",
                style="dim" if notiz.eingehend else "bold #f1c40f",
            ),
            Text(str(len(notiz.verweist_auf) or "-"), justify="right", style="dim"),
            abrufe,
            Text(
                _kuerzen(notiz.beschreibung) if notiz.beschreibung else "-",
                style="" if notiz.beschreibung else "dim",
            ),
        ]

    def _kopf_zeichnen(self) -> None:
        """Setzt den Sortierpfeil und haelt die Spaltenbreite stabil."""
        tabelle = self.query_one("#notizen-daten", DataTable)
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
            # Zahlen zuerst absteigend, Text zuerst aufsteigend - so steht
            # jeweils das Erwartete oben.
            self._absteigend = index in (self._ZEILEN, self._EIN, self._AUS, self._ABRUFE)
        self._kopf_zeichnen()
        self._neu_aufbauen()

    def on_data_table_row_highlighted(self, _ereignis: DataTable.RowHighlighted) -> None:
        # Nur melden, wenn der Anwender wirklich in der Tabelle ist. Beim
        # Befuellen setzt Textual den Cursor selbst auf die erste Zeile und
        # loest dieses Ereignis aus - ohne diese Bedingung stuende sofort eine
        # Notiz rechts, und die Uebersicht, um die es in diesem Tab geht,
        # bekaeme niemand je zu sehen.
        if not self.query_one("#notizen-daten", DataTable).has_focus:
            return
        gewaehlt = self.markierte
        self._gewaehlt = gewaehlt.name if gewaehlt else ""
        self.post_message(self.Ausgewaehlt(gewaehlt))

    def action_zur_uebersicht(self) -> None:
        """Hebt die Auswahl auf, damit rechts wieder die Uebersicht steht."""
        self._gewaehlt = ""
        self.post_message(self.Ausgewaehlt(None))

    def on_search_input_with_history_changed(self, ereignis: Message) -> None:
        wert = getattr(ereignis, "value", None)
        if isinstance(wert, str):
            self.setze_filter(wert)
