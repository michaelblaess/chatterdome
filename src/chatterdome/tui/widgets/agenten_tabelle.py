"""Tabelle der Agenten mit Filterzeile, Ampel und Sortierung per Kopfklick."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable
from textual_widgets import SearchInputWithHistory, vim_navigation_bindings

from chatterdome.i18n import format_datetime, t
from chatterdome.kern.modelle import Agent, geteilte_namen, kennung
from chatterdome.tui.schutz import klartext_oder_nichts
from chatterdome.tui.widgets.agenten_anzeige import (
    AMPEL_FARBE,
    BLINK_STIL,
    _alter,
    _aufgabe,
    _dauer,
    _tokens,
)
from chatterdome.tui.widgets.agenten_kacheln import AgentenKacheln

ORDNER_BREITE = 28
"""Ab hier wird der Pfad in der Tabelle gekuerzt."""

BLINK_TAKT = 0.6
"""Sekunden je Halbtakt der Warnzellen."""

ANSICHT_TABELLE = "tabelle"
ANSICHT_KACHELN = "kacheln"


def _ordner(pfad: str, breite: int = ORDNER_BREITE) -> str:
    """Kuerzt von links - das Ende eines Pfades ist das Aussagekraeftige."""
    if len(pfad) <= breite:
        return pfad
    return "..." + pfad[-(breite - 3) :]


def eindeutig(schluessel: str, vergeben: set[str]) -> str:
    """Haengt einen Zaehler an, solange die Kennung schon vergeben ist.

    Die Zeilenkennung MUSS eindeutig sein - ``DataTable.add_row`` wirft sonst
    ``DuplicateKey``, und zwar aus dem Neuaufbau heraus, der im Sekundentakt
    laeuft. Genau so ist die Oberflaeche am 16.08.2026 gestorben: auf senza
    liefen nach einem misslungenen Neustart zwei Prozesse unter derselben
    Sitzungskennung, damit unter demselben Namen, und ``SENZA/operator`` kam
    zweimal. Der Absturzschirm fing es ab, der naechste Durchlauf warf es
    erneut - eine Schleife, aus der die App nicht mehr herausfand.

    Bewusst wird NICHT entdoppelt: zwei Prozesse auf einer Sitzung sind ein
    echter Zustand, und den soll man sehen. Die Ursache gehoert in
    neustart.mjs behoben, nicht in der Anzeige versteckt. Die Kennung selbst
    bleibt fuer den ersten Treffer unveraendert, damit das Wiederfinden der
    Markierung ueber ``kennung()`` weiter greift.
    """
    kandidat = schluessel
    nummer = 2
    while kandidat in vergeben:
        kandidat = f"{schluessel}#{nummer}"
        nummer += 1
    vergeben.add(kandidat)
    return kandidat


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

    def _on_mount(self, event: events.Mount) -> None:
        # Bewusst _on_mount: in Textual laeuft jeder _on_*-Haken der MRO, ein
        # oeffentliches on_mount verdeckte das einer Ableitung. Die Vim-Ebene
        # haengt am Widget, damit sie nur gilt, solange die Tabelle den Fokus hat.
        if not getattr(self.app, "vim_navigation", False):
            return
        for key, action in vim_navigation_bindings():
            self._bindings.bind(key, action, show=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.zell_hinweise: dict[tuple[int, int], str] = {}
        """(Zeile, Spalte) auf den vollen Text der gekuerzten Zelle."""

    def watch_hover_coordinate(self, old: Coordinate, value: Coordinate) -> None:
        # super() ist Pflicht: die Basis zeichnet die verlassene und die neue
        # Zelle neu. Ohne den Aufruf bleibt die Hervorhebung stehen.
        super().watch_hover_coordinate(old, value)
        # Der Hinweis zeigt den vollen Prompt und den vollen Pfad, beides
        # Fremdtext - und ein Hinweisfenster ist ein Static, wertet Markup
        # also aus. Siehe schutz.py.
        self.tooltip = klartext_oder_nichts(self.zell_hinweise.get((value.row, value.column)))

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
    """Filterzeile plus Tabelle oder Kacheln. Meldet die Auswahl als Message.

    Die Tabelle bleibt auch in der Kachelansicht die eine Quelle der Auswahl: ihr
    Cursor sagt, wer markiert ist, die Kacheln zeigen und setzen ihn nur.
    """

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
    _KONTEXT_SPALTE = 5
    _ORDNER_SPALTE = 11
    """Spalten mit gekuerztem oder umgerechnetem Inhalt - dort haengt der
    volle Wert als Hinweis unter der Maus."""

    def __init__(self, ansicht: str = ANSICHT_TABELLE, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Alles Unbekannte aus der Einstellungsdatei ist die Tabelle.
        self._ansicht = ANSICHT_KACHELN if ansicht == ANSICHT_KACHELN else ANSICHT_TABELLE
        self._agenten: list[Agent] = []
        self._sichtbar: list[Agent] = []
        self._geteilt: set[str] = set()
        """Namen, die auf mehreren Rechnern leben - klein geschrieben."""

        self._filter = ""
        self._sortiert_nach: int | None = 6  # Post - dort steht der Handlungsbedarf
        self._absteigend = True
        self._kopf: list[str] = []
        self._spalten: list[Any] = []
        self._zeilen_schluessel: list[Any] = []
        """Zeilenkennung je sichtbarem Agenten, fuer update_cell beim Blinken."""
        self._blink_an = False

    def compose(self) -> ComposeResult:
        yield SearchInputWithHistory(
            placeholder=t("filter.placeholder"),
            icon="🔍",
            input_id="agenten-filter",
            dropdown_id="agenten-filter-verlauf",
            id="agenten-suche",
        )
        yield AgentenDaten(id="agenten-daten", cursor_type="row", zebra_stripes=True)
        yield AgentenKacheln(id="agenten-kacheln")

    def on_mount(self) -> None:
        self._ansicht_anwenden()
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
        # Blinken von Hand statt ANSI-blink - das ignoriert Windows Terminal.
        self.set_interval(BLINK_TAKT, self._blinken)

    # -- Ansicht --------------------------------------------------------

    @property
    def ansicht(self) -> str:
        """Welche Ansicht gerade zu sehen ist."""
        return self._ansicht

    def ansicht_wechseln(self) -> str:
        """Schaltet zwischen Tabelle und Kacheln um.

        :returns: Die neue Ansicht, zum Speichern in den Einstellungen.
        """
        tabelle = self.query_one("#agenten-daten", AgentenDaten)
        kacheln = self.query_one("#agenten-kacheln", AgentenKacheln)
        # Aus einem Eingabefeld heraus bleibt der Fokus, wo er ist: wer gerade
        # einen Auftrag tippt, soll nach F3 nicht ins Leere weitertippen.
        hatte_fokus = self.app.focused in (tabelle, kacheln, None)
        self._ansicht = ANSICHT_TABELLE if self._ansicht == ANSICHT_KACHELN else ANSICHT_KACHELN
        self._ansicht_anwenden()
        if self._ansicht == ANSICHT_KACHELN:
            kacheln.einblenden()
        if hatte_fokus:
            (kacheln if self._ansicht == ANSICHT_KACHELN else tabelle).focus()
        return self._ansicht

    def _ansicht_anwenden(self) -> None:
        zeige_kacheln = self._ansicht == ANSICHT_KACHELN
        self.query_one("#agenten-daten", AgentenDaten).display = not zeige_kacheln
        kacheln = self.query_one("#agenten-kacheln", AgentenKacheln)
        kacheln.display = zeige_kacheln
        kacheln.animieren(zeige_kacheln)

    # -- Daten ----------------------------------------------------------

    def uebernehmen(self, agenten: list[Agent]) -> None:
        """Ersetzt den Bestand und baut die Tabelle neu."""
        vorher = self.markierter
        self._agenten = agenten
        self._neu_aufbauen(merke=kennung(vorher) if vorher else "")

    def setze_filter(self, text: str) -> None:
        self._filter = text.strip().casefold()
        self._neu_aufbauen()

    def beschriftung(self, a: Agent) -> str:
        """Wie dieser Agent angeschrieben wird - qualifiziert, wenn noetig.

        Lebt der Name auf mehreren Rechnern, steht hier ``Petra@SENZA``, also
        genau die Form, mit der man ihn auch adressiert. Sonst der blosse Name.

        Die eine Stelle fuer diese Entscheidung: Tabelle, Eingabefeld und
        Verlaufsueberschrift muessen dieselbe Beschriftung zeigen, sonst
        steht ueber zwei verschiedenen Gespraechen dieselbe Zeile.
        """
        if a.name.lower() in self._geteilt:
            return f"{a.name}@{a.rechner.upper()}"
        return a.name

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
        markiert = self.markierter
        gemerkt = merke or (kennung(markiert) if markiert else "")

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
        vergeben: set[str] = set()
        self._zeilen_schluessel = []
        for zeile, a in enumerate(sichtbar):
            self._zeilen_schluessel.append(
                tabelle.add_row(*self._zeile(a), key=eindeutig(kennung(a), vergeben))
            )
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
                if kennung(a) == gemerkt:
                    tabelle.move_cursor(row=i)
                    break
        self.query_one("#agenten-kacheln", AgentenKacheln).zeigen(
            sichtbar, self.beschriftung, tabelle.cursor_row
        )
        self.post_message(self.Ausgewaehlt(self.markierter))

    def _zeile(self, a: Agent) -> list[Text]:
        # Lebt der Name auf mehreren Rechnern, steht er hier qualifiziert -
        # dieselbe Form, mit der man ihn dann auch adressiert
        # ("chatterdome send Petra@SENZA"). Der Rechner hat zwar eine eigene
        # Spalte, aber die beantwortet nicht die Frage, WIE man ihn anspricht.
        name = Text(
            self.beschriftung(a) + (" *" if a.selbst else ""),
            style="bold" if a.selbst else "",
        )
        # Verwaist: laeuft, aber seit einem Tag ruehrt sich nichts. Die Ampel
        # bleibt bewusst gruen - die Sitzung KANN Auftraege annehmen, sie tut
        # nur nichts. Markiert wird deshalb das Alter, denn genau das ist der
        # Befund, und dort steht auch der Beleg dafuer.
        alter = self._alter_zelle(a)
        kontext = self._kontext_zelle(a)
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

    # -- Warnzellen und Blinken -----------------------------------------

    def _alter_zelle(self, a: Agent) -> Text:
        # Verwaist: laeuft, aber seit einem Tag ruehrt sich nichts. Markiert
        # und im Takt hervorgehoben wird das Alter, denn dort steht der Beleg.
        verwaist = a.verwaist()
        stil = "dim"
        if verwaist:
            stil = BLINK_STIL if self._blink_an else "bold #e74c3c"
        return Text(("⚠ " if verwaist else "") + _alter(a.letzte_zeit), justify="right",
                    style=stil)

    def _kontext_zelle(self, a: Agent) -> Text:
        if a.kontext_kritisch:
            stil = BLINK_STIL if self._blink_an else "bold red"
        else:
            stil = "yellow" if a.kontext_eng else "dim"
        return Text(_tokens(a.kontext), style=stil, justify="right")

    def _blinken(self) -> None:
        """Schaltet nur die Warnzellen um - kein Neuaufbau, Cursor und Scrollstand bleiben.

        Blinkt, wenn eine Sitzung verwaist ist (Spalte Aktiv) oder ihr Kontext
        kritisch voll ist (Spalte Kontext). Michael am 28.09.2026: die roten
        Zellen fallen zwischen den uebrigen zu wenig auf.
        """
        if self._ansicht == ANSICHT_KACHELN:
            return  # Die Kacheln blinken in ihrem eigenen Takt.
        warnende = [(i, a) for i, a in enumerate(self._sichtbar)
                    if a.verwaist() or a.kontext_kritisch]
        if not warnende:
            self._blink_an = False
            return
        self._blink_an = not self._blink_an
        tabelle = self.query_one("#agenten-daten", DataTable)
        for i, a in warnende:
            if i >= len(self._zeilen_schluessel):
                continue
            zeile = self._zeilen_schluessel[i]
            try:
                if a.verwaist():
                    tabelle.update_cell(zeile, self._spalten[self._ZEIT_SPALTE],
                                        self._alter_zelle(a))
                if a.kontext_kritisch:
                    tabelle.update_cell(zeile, self._spalten[self._KONTEXT_SPALTE],
                                        self._kontext_zelle(a))
            except Exception:
                # Zeile gerade durch einen Neuaufbau ersetzt - der naechste Takt
                # trifft die neue.
                continue

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
        tabelle = self.query_one("#agenten-daten", DataTable)
        self.query_one("#agenten-kacheln", AgentenKacheln).markiere(tabelle.cursor_row)
        self.post_message(self.Ausgewaehlt(self.markierter))

    def on_agenten_kacheln_gewaehlt(self, ereignis: AgentenKacheln.Gewaehlt) -> None:
        self.query_one("#agenten-daten", DataTable).move_cursor(row=ereignis.index)

    def on_agenten_kacheln_aufgerufen(self, ereignis: AgentenKacheln.Aufgerufen) -> None:
        agent = self._bei_zeile(ereignis.index)
        if agent is not None:
            self.post_message(self.Aufgerufen(agent))

    def on_agenten_kacheln_menue_gewuenscht(
        self, ereignis: AgentenKacheln.MenueGewuenscht
    ) -> None:
        agent = self._bei_zeile(ereignis.index)
        if agent is not None:
            self.post_message(self.MenueGewuenscht(agent, ereignis.bei))

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
