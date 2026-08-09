"""Tabelle der Agenten mit Filterzeile, Ampel und Sortierung per Kopfklick."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable
from textual_widgets import SearchInputWithHistory

from claude_sanctuary.i18n import format_datetime, t
from claude_sanctuary.kern.modelle import Agent, Ampel, geteilte_namen

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


ORDNER_BREITE = 28
"""Ab hier wird der Pfad in der Tabelle gekuerzt."""


def _ordner(pfad: str, breite: int = ORDNER_BREITE) -> str:
    """Kuerzt von links - das Ende eines Pfades ist das Aussagekraeftige."""
    if len(pfad) <= breite:
        return pfad
    return "..." + pfad[-(breite - 3) :]


def _alter(zeitpunkt: str, jetzt: datetime | None = None) -> str:
    """Abstand zum letzten Eintrag, kompakt: ``4 min``, ``2 h``, ``3 d``.

    In der Tabelle steht bewusst das Alter und nicht der Zeitstempel: die
    Frage lautet "wie lange ist da nichts mehr passiert", und die beantwortet
    ein Abstand ohne Kopfrechnen - bei einem Drittel der Spaltenbreite. Der
    genaue Zeitpunkt haengt als Hinweis an der Zelle und steht im Detail.
    """
    if not zeitpunkt:
        return "-"
    try:
        wert = datetime.fromisoformat(zeitpunkt.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return "?"
    bezug = jetzt.astimezone() if jetzt is not None else datetime.now().astimezone()
    minuten = int((bezug - wert).total_seconds() // 60)
    if minuten < 1:
        return t("age.now")
    if minuten < 60:
        return f"{minuten} min"
    if minuten < 60 * 24:
        return f"{minuten // 60} h"
    return f"{minuten // (60 * 24)} d"


AUFGABEN_BREITE = 30
"""Deckel fuer die Aufgabenspalte.

Gemessen an einem Fenster von 120 Zeichen: die Tabelle sieht davon rund 70,
und bei 40 Zeichen Aufgabe schiebt allein diese Spalte Kontext und Post aus
dem Bild. Bei 30 bleiben sie stehen, und kurze Auftraege brauchen ohnehin
weniger - die Spalte waechst nur so weit wie ihr laengster Text.
"""


def _aufgabe(text: str, breite: int = AUFGABEN_BREITE) -> str:
    """Kuerzt von rechts - der Anfang eines Auftrags traegt die Aussage.

    Ohne Deckel wuerde die Spalte so breit wie der laengste Auftragstext,
    und die Tabelle waere nur noch seitlich zu lesen. Der volle Text steht
    im Hinweis unter der Maus und in der Detailansicht.
    """
    einzeilig = " ".join(text.split())
    if len(einzeilig) <= breite:
        return einzeilig
    return einzeilig[: breite - 3].rstrip() + "..."


class AgentenDaten(DataTable[Any]):
    """DataTable, die Doppel- und Rechtsklick als eigene Nachricht meldet.

    Der Rechtsklick MUSS hier abgefangen werden: Textuals ``_on_click``
    prueft die Maustaste nicht, verschiebt den Cursor und postet unter
    Umstaenden ``RowSelected``. ``event.stop()`` genuegt dafuer nicht - es
    unterbindet nur das Bubbling, nicht die Aufrufkette entlang der MRO.
    Dafuer ist ``prevent_default()`` da, und ein ``super()``-Aufruf darf
    NICHT dazu, weil Textual die Basis ohnehin selbst aufruft.

    Ausserdem zeigt sie den vollen Inhalt gekuerzter Zellen als Hinweis
    unter der Maus. Textual kennt keine Hinweise je Textabschnitt - der
    Hinweis gehoert immer dem ganzen Widget, also wird er beim Wandern der
    Maus umgeschrieben.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.zell_hinweise: dict[tuple[int, int], str] = {}
        """(Zeile, Spalte) auf den vollen Text der gekuerzten Zelle."""

    def watch_hover_coordinate(self, old: Coordinate, value: Coordinate) -> None:
        # super() ist Pflicht: die Basis zeichnet die verlassene und die neue
        # Zelle neu. Ohne den Aufruf bleibt die Hervorhebung stehen.
        super().watch_hover_coordinate(old, value)
        self.tooltip = self.zell_hinweise.get((value.row, value.column))

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

    # Reihenfolge nach Betriebssicht: wer, wo, woran, seit wann nichts mehr,
    # dann die Kennzahlen. Die statischen Angaben (Modell, Version, Ordner,
    # Werkzeug) stehen hinten - sie beantworten keine Frage im Minutentakt.
    # Nur Spalten in diesem Verzeichnis sind sortierbar.
    _SORTIER: ClassVar[dict[int, Callable[[Agent], Any]]] = {
        1: lambda a: a.name.casefold(),
        2: lambda a: a.rechner.casefold(),
        4: lambda a: a.letzte_zeit,
        5: lambda a: a.kontext,
        6: lambda a: a.post,
        7: lambda a: a.laufzeit_ms,
        8: lambda a: a.tokens,
        9: lambda a: (a.modell or "").casefold(),
        10: lambda a: (a.version or "").casefold(),
        11: lambda a: a.cwd.casefold(),
    }
    """Spalte 3 (Aufgabe) und 12 (Werkzeug) sind freier Text - eine
    alphabetische Sortierung danach ordnet nichts Sinnvolles."""

    _AUFGABEN_SPALTE = 3
    _ZEIT_SPALTE = 4
    _ORDNER_SPALTE = 11
    """Spalten mit gekuerztem oder umgerechnetem Inhalt - dort haengt der
    volle Wert als Hinweis unter der Maus."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agenten: list[Agent] = []
        self._sichtbar: list[Agent] = []
        self._geteilt: set[str] = set()
        """Namen, die auf mehreren Rechnern leben - klein geschrieben."""

        self._filter = ""
        self._sortiert_nach: int | None = 6  # Post - dort steht der Handlungsbedarf
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
            t("col.state"), t("col.name"), t("col.host"), t("col.task"),
            t("col.last_seen"), t("col.context"), t("col.post"), t("col.uptime"),
            t("col.tokens"), t("col.model"), t("col.version"), t("col.dir"),
            t("col.tool"),
        ]
        self._spalten = list(tabelle.add_columns(*self._kopf))
        # Zwei feste Spalten: beim Blaettern nach rechts muss erkennbar
        # bleiben, zu wem die Zeile gehoert - die Ampel allein genuegt nicht.
        tabelle.fixed_columns = 2
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

        # Ueber ALLE Agenten, nicht nur die sichtbaren: filtert man auf einen
        # Rechner, waere der Name dort scheinbar eindeutig - und genau dann
        # braucht man den Hinweis am dringendsten.
        self._geteilt = geteilte_namen(self._agenten)

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
        hinweise: dict[tuple[int, int], str] = {}
        for zeile, a in enumerate(sichtbar):
            tabelle.add_row(*self._zeile(a), key=f"{a.rechner}/{a.name}")
            # Nur wo wirklich gekuerzt wurde - sonst haengt an jeder Zelle ein
            # Hinweis, der dasselbe sagt wie die Zelle selbst.
            if a.cwd and len(a.cwd) > ORDNER_BREITE:
                hinweise[(zeile, self._ORDNER_SPALTE)] = a.cwd
            if a.aufgabe:
                hinweise[(zeile, self._AUFGABEN_SPALTE)] = " ".join(a.aufgabe.split())
            if a.letzte_zeit:
                # Die Spalte zeigt das Alter - der genaue Zeitpunkt hier.
                hinweise[(zeile, self._ZEIT_SPALTE)] = format_datetime(a.letzte_zeit)
        if isinstance(tabelle, AgentenDaten):
            tabelle.zell_hinweise = hinweise

        if gemerkt:
            for i, a in enumerate(sichtbar):
                if a.name == gemerkt:
                    tabelle.move_cursor(row=i)
                    break
        self.post_message(self.Ausgewaehlt(self.markierter))

    def _zeile(self, a: Agent) -> list[Text]:
        # Lebt der Name auf mehreren Rechnern, steht er hier qualifiziert -
        # dieselbe Form, mit der man ihn dann auch adressiert
        # ("sanctuary send Petra@SENZA"). Der Rechner hat zwar eine eigene
        # Spalte, aber die beantwortet nicht die Frage, WIE man ihn anspricht.
        geteilt = a.name.lower() in self._geteilt
        beschriftung = f"{a.name}@{a.rechner.upper()}" if geteilt else a.name
        name = Text(
            beschriftung + (" *" if a.selbst else ""),
            style="bold" if a.selbst else "",
        )
        # Verwaist: laeuft, aber seit einem Tag ruehrt sich nichts. Die Ampel
        # bleibt bewusst gruen - die Sitzung KANN Auftraege annehmen, sie tut
        # nur nichts. Markiert wird deshalb das Alter, denn genau das ist der
        # Befund, und dort steht auch der Beleg dafuer.
        verwaist = a.verwaist()
        alter = Text(
            ("⚠ " if verwaist else "") + _alter(a.letzte_zeit),
            justify="right",
            style="bold #e74c3c" if verwaist else "dim",
        )
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
            Text(_aufgabe(a.aufgabe) if a.aufgabe else "-", style="" if a.aufgabe else "dim"),
            alter,
            kontext,
            post,
            laufzeit,
            Text(_tokens(a.tokens), justify="right", style="dim"),
            Text(a.modell or "-", style="" if a.modell else "dim"),
            Text(a.version or "-", style="dim"),
            Text(_ordner(a.cwd), style="dim"),
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
