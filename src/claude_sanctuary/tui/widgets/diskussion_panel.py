"""Der Reiter "Diskussion": Formular zum Einrichten, danach der Chat.

Ohne laufende Diskussion steht hier das Formular, mit ihr der Verlauf wie im
Messenger - PRO links, CONTRA rechts, von oben nach unten zu lesen. Die neutrale
Zusammenfassung steht UNTER dem Chat und nie darin (Michael, 28.09.2026: "keine
Zusammenfassungen im Chat, sondern wirklich eine Diskussion").

Das Panel startet nichts selbst. Es meldet ``Starten`` und ``Anhalten`` an die
App, die den Ablauf in einem Worker fuehrt und die Ereignisse zurueckreicht.
Vorher stand das Formular in einem modalen Dialog hinter der Taste a.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from rich.style import Style
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static, TextArea
from textual_widgets import StatusItem

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.debatte import (
    CONTRA,
    MODELLE,
    PRO,
    VORGABE_MODELL,
    Beitrag,
    Diskussion,
    Teilnehmer,
    Verbrauch,
    absaetze,
)
from claude_sanctuary.kern.diskussionsarchiv import Eintrag
from claude_sanctuary.kern.modelle import Agent
from claude_sanctuary.tui.widgets.status_zeile import _tokens


def modell_name(modell: str) -> str:
    """Kurzer Anzeigename eines Modell-Kurznamens, leer ist die Voreinstellung."""
    return modell.capitalize() if modell else t("discussion.model_default_short")


def _modell_auswahl() -> list[tuple[str, str]]:
    # Die Schluessel stehen ausgeschrieben da, damit die Pruefung auf unbenutzte
    # Uebersetzungen sie findet.
    texte = {"": t("discussion.model_default"), "haiku": t("discussion.model_haiku"),
             "sonnet": t("discussion.model_sonnet"), "opus": t("discussion.model_opus")}
    return [(texte[m], m) for m in MODELLE]


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BALKEN_BREITE = 18
BALKEN_BLOCK = 5


def _balken(schritt: int) -> str:
    """Ein Block, der im Balken hin und her laeuft - fuer Arbeit ohne bekannte Dauer."""
    weg = BALKEN_BREITE - BALKEN_BLOCK
    stelle = schritt % (2 * weg)
    stelle = stelle if stelle <= weg else 2 * weg - stelle
    return "▱" * stelle + "▰" * BALKEN_BLOCK + "▱" * (weg - stelle)


def _dauer(sekunden: float) -> str:
    ganz = int(sekunden)
    return f"{ganz // 60}:{ganz % 60:02d}"


class _Laeuft(Static):
    """Eine Zeile, die zeigt, dass gerade gearbeitet wird - mit Animation und Uhr.

    Zwei Arten: ``schreibt`` ist die Tipp-Anzeige in der Blase des Redners
    (laufende Punkte), sonst Spinner, Laufbalken und Text. Einen echten
    Fortschritt gibt es nicht: wie lange eine Recherche dauert, weiss niemand
    vorher, und ein Balken, der bei 90 % haengt, luegt.
    """

    TAKT = 0.12

    def __init__(self, text: str, *, schreibt: bool = False, classes: str = "") -> None:
        super().__init__("", classes=f"disk-laeuft {classes}".strip())
        self.text = text
        self._schreibt = schreibt
        self._schritt = 0
        self._beginn = time.monotonic()

    def on_mount(self) -> None:
        self._zeichnen()
        self.set_interval(self.TAKT, self._weiter)

    @property
    def sekunden(self) -> float:
        return time.monotonic() - self._beginn

    def _weiter(self) -> None:
        self._schritt += 1
        self._zeichnen()

    def _zeichnen(self) -> None:
        self.update(self.zeile())

    def zeile(self) -> Text:
        """Der aktuelle Stand der Anzeige."""
        farbe = self.app.theme_variables.get("accent", "magenta")
        zeile = Text()
        if self._schreibt:
            zeile.append(self.text, style="italic")
            zeile.append("  ")
            # Drei Punkte, die nacheinander aufleuchten - wie im Messenger.
            hell = (self._schritt // 3) % 3
            for i in range(3):
                zeile.append("● ", style=f"bold {farbe}" if i == hell else "dim")
        else:
            zeile.append(f"{SPINNER[self._schritt % len(SPINNER)]} ", style=f"bold {farbe}")
            zeile.append(self.text)
            zeile.append(f"  {_balken(self._schritt)}", style=farbe)
        zeile.append(f"  {_dauer(self.sekunden)}", style="dim")
        return zeile


class _ArchivTabelle(DataTable[Any]):
    """Die Uebersicht, die den Rechtsklick meldet.

    Abgefangen wie in ``AgentenDaten``: Textuals eigener Klick-Handler setzt nur
    den Cursor, von der rechten Maustaste erfaehrt sonst niemand.
    """

    class Rechtsklick(Message):
        def __init__(self, zeile: int, bei: tuple[int, int]) -> None:
            super().__init__()
            self.zeile = zeile
            self.bei = bei

    async def _on_click(self, event: events.Click) -> None:
        zeile = event.style.meta.get("row", -1)
        if event.button != 3 or not isinstance(zeile, int) or zeile < 0:
            return
        event.prevent_default()
        event.stop()
        self.move_cursor(row=zeile)
        self.post_message(self.Rechtsklick(zeile, (event.screen_x, event.screen_y)))


MAX_NEU = 6
"""Mehr frische Fenster auf einmal braucht keine Diskussion, und jedes kostet."""

AUTO = "auto"
"""Wert der Seitenauswahl, wenn der Moderator verteilen soll."""


@dataclass
class DiskussionsAuftrag:
    """Was das Formular an die App gibt."""

    diskussion: Diskussion
    """Mit den laufenden Agenten als Teilnehmern."""
    neu: list[Teilnehmer] = field(default_factory=list)
    """Je frische Sitzung ein Platzhalter mit Seite, siehe ``debatte_ablauf.ausfuehren``."""
    ohne_kontext: bool = False
    wiederbeleben: list[Teilnehmer] = field(default_factory=list)
    """Beim Fortsetzen: Teilnehmer, deren Sitzung nicht mehr laeuft."""
    protokoll: str = ""
    """Beim Fortsetzen: die Markdown-Datei, die weitergeschrieben wird."""


class _AgentZeile(Horizontal):
    """Ein laufender Agent zum Ankreuzen, daneben seine Seite."""

    def __init__(self, agent: Agent, angekreuzt: bool, seite: str, **kwargs: Any) -> None:
        super().__init__(classes="disk-agent-zeile", **kwargs)
        self.agent = agent
        self._angekreuzt = angekreuzt
        self._seite = seite

    def compose(self) -> ComposeResult:
        yield Checkbox(
            t("discussion.agent_entry", name=self.agent.name,
              rechner=self.agent.rechner.upper(), status=self.agent.status),
            value=self._angekreuzt, compact=True, classes="disk-agent-haken",
        )
        yield Select([(t("discussion.side_auto"), AUTO), ("PRO", PRO), ("CONTRA", CONTRA)],
                     value=self._seite, allow_blank=False, compact=True,
                     classes="disk-agent-seite")

    # Der Zustand steht in der Zeile selbst und wird ueber die Aenderungen
    # nachgefuehrt, NICHT aus den Feldern gelesen. Frisch eingehaengt hat die
    # Zeile ihre Kinder noch nicht, und eine Pruefung genau dazwischen warf
    # NoMatches - am 28.09.2026 bei Michael, zweimal, einmal als Absturz.

    @on(Checkbox.Changed, ".disk-agent-haken")
    def _haken_geaendert(self, ereignis: Checkbox.Changed) -> None:
        self._angekreuzt = bool(ereignis.value)

    @on(Select.Changed, ".disk-agent-seite")
    def _seite_geaendert(self, ereignis: Select.Changed) -> None:
        self._seite = str(ereignis.value)

    @property
    def angekreuzt(self) -> bool:
        return self._angekreuzt

    @property
    def seite(self) -> str:
        return self._seite


class DiskussionsPanel(Vertical):
    """Formular und Chat einer Diskussion."""

    DEFAULT_CSS = """
    DiskussionsPanel {
        height: 1fr;
    }
    DiskussionsPanel #disk-formular {
        height: 1fr;
        padding: 1 2;
    }
    DiskussionsPanel .disk-zeile {
        height: 1;
        margin-bottom: 1;
    }
    DiskussionsPanel .disk-zeile Label {
        width: 18;
    }
    /* Das Thema ist oft ein ganzer Satz mit Kontext - drei Zeilen, umbrechend. */
    DiskussionsPanel .disk-zeile.disk-thema-zeile {
        height: 3;
    }
    DiskussionsPanel #disk-thema {
        width: 1fr;
        height: 3;
    }
    DiskussionsPanel .disk-position {
        width: 1fr;
        margin-right: 2;
    }
    DiskussionsPanel .disk-seite {
        width: auto;
        padding: 0 1 0 0;
        text-style: bold;
    }
    DiskussionsPanel .disk-seite-pro {
        color: $primary;
    }
    DiskussionsPanel .disk-seite-contra {
        color: $accent;
    }
    /* Die Erklaerung sitzt unter den Feldern und nimmt den Abstand der
       Zeile ein - das Formular wird dadurch nicht hoeher. */
    DiskussionsPanel #disk-positionen {
        margin-bottom: 0;
    }
    DiskussionsPanel #disk-positionen-hinweis {
        height: auto;
        margin: 0 0 1 18;
    }
    DiskussionsPanel #disk-format, DiskussionsPanel #disk-modell {
        width: 32;
    }
    DiskussionsPanel .disk-zahl {
        width: 8;
    }
    DiskussionsPanel .disk-einheit {
        width: auto;
        padding: 0 2 0 1;
        color: $text-muted;
    }
    DiskussionsPanel #disk-agenten {
        height: auto;
        max-height: 8;
        border: round $surface-lighten-2;
        padding: 0 1;
        margin-bottom: 1;
    }
    DiskussionsPanel .disk-agent-zeile {
        height: 1;
    }
    DiskussionsPanel .disk-agent-haken {
        width: 1fr;
    }
    DiskussionsPanel .disk-agent-seite {
        width: 20;
    }
    DiskussionsPanel .disk-leise {
        color: $text-muted;
    }
    DiskussionsPanel #disk-grund {
        color: $warning;
    }
    DiskussionsPanel .disk-knoepfe {
        height: 3;
        align: left middle;
    }
    DiskussionsPanel .disk-knoepfe Button {
        margin: 0 2 0 0;
    }

    /* -- Chat -- */
    DiskussionsPanel #disk-chat-raum {
        display: none;
        height: 1fr;
    }
    DiskussionsPanel.laeuft #disk-formular,
    DiskussionsPanel.fertig #disk-formular {
        display: none;
    }
    DiskussionsPanel.laeuft #disk-chat-raum,
    DiskussionsPanel.fertig #disk-chat-raum {
        display: block;
    }
    DiskussionsPanel #disk-kopf {
        height: auto;
        padding: 0 2;
        border-bottom: solid $surface-lighten-2;
    }
    DiskussionsPanel #disk-steuerung {
        height: 3;
        padding: 0 2;
    }
    DiskussionsPanel #disk-steuerung Button {
        margin: 0 2 0 0;
    }
    DiskussionsPanel #disk-chat {
        height: 1fr;
        padding: 1 2;
    }
    /* Der Abstand steht in JEDER Regel vollstaendig: Textual fuehrt margin
       als eine Eigenschaft, eine Langform in der spezifischeren Regel wuerde
       den unteren Abstand der Basisregel loeschen (belegt am 09.08.2026). */
    DiskussionsPanel .disk-blase {
        height: auto;
        padding: 0 1;
        background: $panel;
        margin: 0 16 1 0;
    }
    DiskussionsPanel .disk-blase.disk-pro {
        border-left: thick $primary;
        margin: 0 16 1 0;
    }
    DiskussionsPanel .disk-blase.disk-contra {
        border-right: thick $accent;
        margin: 0 0 1 16;
    }
    DiskussionsPanel .disk-blase.disk-team {
        border-left: thick $secondary;
        margin: 0 8 1 0;
    }
    /* Laufende Anzeigen: Spinner, Laufbalken, Tipp-Punkte (siehe _Laeuft). */
    DiskussionsPanel .disk-laeuft {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    DiskussionsPanel .disk-tippt {
        background: $panel;
    }
    DiskussionsPanel .disk-tippt.disk-pro {
        border-left: thick $primary;
        margin: 0 16 1 0;
    }
    DiskussionsPanel .disk-tippt.disk-contra {
        border-right: thick $accent;
        margin: 0 0 1 16;
        text-align: right;
    }
    DiskussionsPanel .disk-tippt.disk-team {
        border-left: thick $secondary;
        margin: 0 8 1 0;
    }
    DiskussionsPanel .disk-meldung {
        height: auto;
        color: $text-muted;
        text-style: italic;
        content-align: center middle;
        width: 1fr;
        margin: 0 0 1 0;
    }
    DiskussionsPanel #disk-zusammenfassung-raum {
        display: none;
        height: auto;
        max-height: 12;
        border-top: solid $surface-lighten-2;
        padding: 0 2;
    }
    DiskussionsPanel #disk-zusammenfassung-raum.da {
        display: block;
    }
    DiskussionsPanel #disk-weiter {
        width: 8;
        margin: 1 1 0 0;
    }
    DiskussionsPanel #disk-weiter-raum {
        height: auto;
        padding: 0 2 1 2;
    }
    DiskussionsPanel #disk-weiter-info {
        height: 3;
    }
    /* Hinweis des Moderators: mittig, nicht auf einer der beiden Seiten. */
    DiskussionsPanel .disk-moderator {
        height: auto;
        padding: 0 1;
        margin: 0 8 1 8;
        border: round $warning;
        background: $panel;
    }
    DiskussionsPanel #disk-weiter-modell {
        width: 40;
        margin: 1 2 0 0;
    }
    DiskussionsPanel #disk-weiter-einheit {
        width: auto;
        margin: 1 2 0 0;
        color: $text-muted;
    }

    /* -- Archiv: immer sichtbar, unter dem Formular oder bei breitem
       Fenster daneben (Klasse "breit", gesetzt in on_resize) -- */
    DiskussionsPanel #disk-start {
        height: 1fr;
        layout: vertical;
    }
    DiskussionsPanel.breit #disk-start {
        layout: horizontal;
    }
    DiskussionsPanel #disk-archiv-raum {
        height: auto;
        max-height: 10;
        padding: 0 2;
        border-top: solid $surface-lighten-2;
    }
    DiskussionsPanel.breit #disk-archiv-raum {
        width: 2fr;
        height: 1fr;
        max-height: 100%;
        padding: 1 2;
        border-top: none;
        border-left: solid $surface-lighten-2;
    }
    DiskussionsPanel.niedrig #disk-archiv-raum {
        display: none;
    }
    DiskussionsPanel.breit #disk-formular {
        width: 3fr;
    }
    DiskussionsPanel.laeuft #disk-start,
    DiskussionsPanel.fertig #disk-start {
        display: none;
    }
    DiskussionsPanel #disk-archiv {
        height: auto;
    }
    DiskussionsPanel.breit #disk-archiv {
        height: 1fr;
    }
    """

    # Ohne uebersetzten Text: die Klasse entsteht, bevor die Sprache geladen ist.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "zur_uebersicht", show=False),
    ]

    class Starten(Message):
        """Das Formular ist vollstaendig, die App soll den Ablauf starten."""

        def __init__(self, auftrag: DiskussionsAuftrag) -> None:
            super().__init__()
            self.auftrag = auftrag

    class Anhalten(Message):
        """Der Knopf "Anhalten" wurde gedrueckt."""

    class Oeffnen(Message):
        """Eine Diskussion aus dem Archiv soll angezeigt werden."""

        def __init__(self, kennung: int) -> None:
            super().__init__()
            self.kennung = kennung

    class Fortsetzen(Message):
        """Die angezeigte Diskussion soll um ``runden`` Runden weitergehen."""

        def __init__(self, diskussion: Diskussion, runden: int, protokoll: str,
                     modell: str, hinweis: str = "", mit_kontext: bool = False) -> None:
            super().__init__()
            self.diskussion = diskussion
            self.runden = runden
            self.protokoll = protokoll
            self.modell = modell
            self.hinweis = hinweis
            """Neue Informationen fuer die Teilnehmer, leer fuer keine."""
            self.mit_kontext = mit_kontext

    class ArchivMenue(Message):
        """Rechtsklick auf eine gespeicherte Diskussion."""

        def __init__(self, kennung: int, bei: tuple[int, int]) -> None:
            super().__init__()
            self.kennung = kennung
            self.bei = bei

    class Kennzahlen(Message):
        """Runde, Redner oder Verbrauch haben sich geaendert - fuer die Statuszeile."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agenten: list[Agent] = []
        self._zeilen: list[_AgentZeile] = []
        """Die aktuellen Zeilen. NICHT per query ermitteln: remove_children wirkt
        verzoegert, und eine Abfrage direkt nach dem Neuaufbau fand jeden Agenten
        doppelt ("Ein Teilnehmer steht doppelt in der Liste")."""
        self._generation = 0
        """Zaehlt die Neuaufbauten der Agentenliste - IDs muessen eindeutig bleiben."""
        self._diskussion: Diskussion | None = None
        self._neu: list[Teilnehmer] = []
        """Platzhalter der frischen Agenten, bis ihre Namen bekannt sind."""
        self._runde = 0
        self._redner = ""
        self._zustand = ""
        self._protokoll = ""
        self._verbrauch = Verbrauch()
        self._archiv: list[Eintrag] = []
        self._laeufer: dict[str, _Laeuft] = {}
        """Die laufenden Anzeigen im Chat: Start, Recherche je Name, Tippen, Zusammenfassung."""
        self._recherche_gesamt = 0

    # -- Aufbau ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="disk-start"):
            with VerticalScroll(id="disk-formular"):
                with Horizontal(classes="disk-zeile disk-thema-zeile"):
                    yield Label(t("discussion.topic"))
                    yield TextArea(placeholder=t("discussion.topic_placeholder"), id="disk-thema",
                                   compact=True, soft_wrap=True, show_line_numbers=False,
                                   tab_behavior="focus")
                # Jedes Feld mit eigener Seitenbeschriftung und darunter die
                # Erklaerung - "PRO, z.B. Unity (leer = Ja)" als Platzhalter allein
                # war Michael am 29.09.2026 nicht verstaendlich.
                with Horizontal(classes="disk-zeile", id="disk-positionen"):
                    yield Label(t("discussion.positions"))
                    yield Static("PRO", classes="disk-seite disk-seite-pro")
                    yield Input(placeholder=t("discussion.position_pro_placeholder"),
                                id="disk-position-pro", classes="disk-position", compact=True)
                    yield Static("CONTRA", classes="disk-seite disk-seite-contra")
                    yield Input(placeholder=t("discussion.position_contra_placeholder"),
                                id="disk-position-contra", classes="disk-position", compact=True)
                yield Static(t("discussion.positions_hint"), id="disk-positionen-hinweis",
                             classes="disk-leise")
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.format"))
                    yield Select(
                        [(t("discussion.format_debate"), "diskussion"),
                         (t("discussion.format_team"), "team")],
                        value="diskussion", allow_blank=False, id="disk-format", compact=True,
                    )
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.limit"))
                    yield Input("3", type="integer", id="disk-runden", classes="disk-zahl",
                                compact=True)
                    yield Static(t("discussion.rounds"), classes="disk-einheit")
                    yield Input("0", type="number", id="disk-dauer", classes="disk-zahl",
                                compact=True)
                    yield Static(t("discussion.minutes"), classes="disk-einheit")
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.model"))
                    yield Select(_modell_auswahl(), value=VORGABE_MODELL, allow_blank=False,
                                 id="disk-modell", compact=True)
                    yield Static(t("discussion.model_hint"), classes="disk-einheit")
                yield Static(t("discussion.running_agents"))
                with VerticalScroll(id="disk-agenten"):
                    yield Static(t("discussion.no_agents"), id="disk-keine", classes="disk-leise")
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.new_agents"))
                    yield Input("0", type="integer", id="disk-neu", classes="disk-zahl",
                                compact=True)
                    yield Static(t("discussion.new_hint"), classes="disk-einheit")
                yield Checkbox(t("discussion.research"), value=True, id="disk-recherche",
                               compact=True)
                yield Checkbox(t("discussion.with_context"), value=False,
                               id="disk-mit-kontext", compact=True)
                yield Static("", id="disk-vorschau", classes="disk-leise")
                yield Static("", id="disk-grund")
                with Horizontal(classes="disk-knoepfe"):
                    yield Button(t("discussion.start"), variant="primary", id="disk-starten")
            with Vertical(id="disk-archiv-raum"):
                yield Static(t("discussion.archive"), id="disk-archiv-titel")
                yield _ArchivTabelle(id="disk-archiv", cursor_type="row", zebra_stripes=True)
        with Vertical(id="disk-chat-raum"):
            yield Static("", id="disk-kopf")
            with Horizontal(id="disk-steuerung"):
                # Zur Uebersicht ganz links: der Weg zurueck steht, wo man ihn sucht.
                yield Button(t("discussion.new"), variant="primary", id="disk-neue")
                yield Button(t("discussion.stop"), variant="error", id="disk-anhalten")
                yield Button(t("discussion.continue"), variant="success", id="disk-fortsetzen")
                yield Input("3", type="integer", id="disk-weiter", compact=True)
                yield Static(t("discussion.more_rounds"), id="disk-weiter-einheit")
                yield Select(_modell_auswahl(), value=VORGABE_MODELL, allow_blank=False,
                             id="disk-weiter-modell", compact=True)
            with Vertical(id="disk-weiter-raum"):
                yield Static(t("discussion.more_info"), classes="disk-leise")
                yield TextArea(id="disk-weiter-info", compact=True, soft_wrap=True,
                               show_line_numbers=False, tab_behavior="focus",
                               placeholder=t("discussion.more_info_placeholder"))
                yield Checkbox(t("discussion.with_context"), value=False,
                               id="disk-weiter-kontext", compact=True)
            yield VerticalScroll(id="disk-chat")
            with VerticalScroll(id="disk-zusammenfassung-raum"):
                yield Static("", id="disk-zusammenfassung")

    def on_mount(self) -> None:
        tabelle = self.query_one("#disk-archiv", DataTable)
        # Das Thema zuletzt: es ist das laengste Feld und schoebe sonst
        # die kurzen Spalten aus dem Bild.
        tabelle.add_columns(t("discussion.col_date"), t("discussion.col_agents"),
                            t("discussion.col_rounds"), t("discussion.col_tokens"),
                            t("discussion.col_model"), t("discussion.col_topic"))
        self._steuerung_zeigen(laeuft=True)
        self._pruefen()

    BREIT_AB = 140
    """Ab dieser Breite steht das Archiv neben dem Formular statt darunter."""

    NIEDRIG_UNTER = 20
    """Darunter hat das Archiv unter dem Formular keinen Platz - es entfaellt dann,
    das Formular geht vor (Test ``test_formular_passt_auf_100_mal_30``)."""

    def on_resize(self, ereignis: events.Resize) -> None:
        breit = ereignis.size.width >= self.BREIT_AB
        self.set_class(breit, "breit")
        self.set_class(not breit and ereignis.size.height < self.NIEDRIG_UNTER, "niedrig")

    # -- Archiv ---------------------------------------------------------

    def archiv_setzen(self, eintraege: list[Eintrag]) -> None:
        """Fuellt die Uebersicht der gespeicherten Diskussionen, neueste zuerst."""
        self._archiv = list(eintraege)
        tabelle = self.query_one("#disk-archiv", DataTable)
        tabelle.clear()
        for e in eintraege:
            thema = e.thema if len(e.thema) <= 50 else f"{e.thema[:47]}..."
            tabelle.add_row(_datum(e.beginn), ", ".join(e.teilnehmer), str(e.runden),
                            _tokens(e.tokens), modell_name(e.modell), thema,
                            key=str(e.kennung))
        self.query_one("#disk-archiv-titel", Static).update(
            t("discussion.archive") if eintraege else t("discussion.archive_empty"))

    @on(DataTable.RowSelected, "#disk-archiv")
    def _archiv_gewaehlt(self, ereignis: DataTable.RowSelected) -> None:
        if ereignis.row_key.value is not None:
            self.post_message(self.Oeffnen(int(ereignis.row_key.value)))

    @on(_ArchivTabelle.Rechtsklick)
    def _archiv_rechtsklick(self, ereignis: _ArchivTabelle.Rechtsklick) -> None:
        if 0 <= ereignis.zeile < len(self._archiv):
            self.post_message(self.ArchivMenue(self._archiv[ereignis.zeile].kennung, ereignis.bei))

    def zeigen(self, diskussion: Diskussion, protokoll: str) -> None:
        """Zeigt eine abgeschlossene Diskussion aus dem Archiv im Chat."""
        self.beginnen(diskussion, [])
        self.fertig(diskussion, diskussion.ende, protokoll)

    # -- Agentenliste ---------------------------------------------------

    def agenten_setzen(self, agenten: list[Agent]) -> None:
        """Nimmt den aktuellen Bestand. Baut die Liste nur neu, wenn sich Namen aendern.

        Haken und Seiten ueberleben den Neuaufbau ueber den Namen - sonst loeschte
        jede Aktualisierung des Bestands, was der Anwender gerade eingestellt hat.
        """
        neu = [a for a in agenten if not a.selbst]
        if [(a.name, a.rechner) for a in neu] == [(a.name, a.rechner) for a in self._agenten]:
            return
        vorher = {(z.agent.name, z.agent.rechner): (z.angekreuzt, z.seite)
                  for z in self._zeilen}
        self._agenten = neu
        self._generation += 1
        liste = self.query_one("#disk-agenten", VerticalScroll)
        liste.remove_children()
        if not neu:
            liste.mount(Static(t("discussion.no_agents"), classes="disk-leise"))
        self._zeilen = []
        for i, agent in enumerate(neu):
            angekreuzt, seite = vorher.get((agent.name, agent.rechner), (False, AUTO))
            zeile = _AgentZeile(agent, angekreuzt, seite,
                                id=f"disk-agent-{self._generation}-{i}")
            self._zeilen.append(zeile)
            liste.mount(zeile)
        # Waehrend einer Diskussion ist das Formular verdeckt und wird nicht
        # geprueft - der Bestand aktualisiert sich aber weiter im Takt.
        if not self.has_class("laeuft"):
            self.call_after_refresh(self._pruefen)

    # -- Formular auswerten ---------------------------------------------

    def _zahl(self, feld_id: str) -> float | None:
        roh = self.query_one(f"#{feld_id}", Input).value.strip().replace(",", ".")
        try:
            return float(roh)
        except ValueError:
            return None

    def auftrag(self) -> tuple[DiskussionsAuftrag | None, str]:
        """Baut den Auftrag aus dem Formular, oder nennt den ersten Grund, warum nicht."""
        # Zeilenumbrueche aus dem Feld werden zu Leerzeichen: das Thema landet in
        # jeder Anweisung und im Kopf des Chats, dort soll es ein Satz bleiben.
        thema = " ".join(self.query_one("#disk-thema", TextArea).text.split())
        runden = self._zahl("disk-runden")
        dauer = self._zahl("disk-dauer")
        neu = self._zahl("disk-neu")
        if not thema:
            return None, t("discussion.missing_topic")
        if runden is None or runden < 1 or runden != int(runden):
            return None, t("discussion.bad_rounds")
        if dauer is None or dauer < 0:
            return None, t("discussion.bad_minutes")
        if neu is None or neu < 0 or neu != int(neu) or neu > MAX_NEU:
            return None, t("discussion.bad_new", maximum=MAX_NEU)
        zeilen = [z for z in self._zeilen if z.angekreuzt]
        if len(zeilen) + int(neu) < 2:
            return None, t("discussion.too_few")

        format_wert = str(self.query_one("#disk-format", Select).value)
        mit_seiten = format_wert == "diskussion"
        diskussion = Diskussion(
            thema=thema,
            teilnehmer=[Teilnehmer(z.agent.name,
                                   seite=z.seite if mit_seiten and z.seite != AUTO else "")
                        for z in zeilen],
            format=format_wert,
            runden=int(runden),
            modell=str(self.query_one("#disk-modell", Select).value),
            dauer_minuten=float(dauer),
            recherche=self.query_one("#disk-recherche", Checkbox).value,
            positionen=(self.query_one("#disk-position-pro", Input).value.strip(),
                        self.query_one("#disk-position-contra", Input).value.strip()),
        )
        platzhalter = [Teilnehmer(t("discussion.new_placeholder", nummer=i + 1))
                       for i in range(int(neu))]
        # Seiten jetzt verteilen, in der Reihenfolge des Moderators: erst die
        # laufenden, dann die frischen. Die frischen behalten ihre Seite, wenn
        # sie spaeter ihren echten Namen bekommen.
        diskussion.teilnehmer = diskussion.teilnehmer + platzhalter
        diskussion.seiten_verteilen()
        grund = diskussion.pruefen()
        if grund:
            return None, grund
        anzahl = len(zeilen)
        neu_teilnehmer = diskussion.teilnehmer[anzahl:]
        diskussion.teilnehmer = diskussion.teilnehmer[:anzahl]
        return DiskussionsAuftrag(
            diskussion=diskussion,
            neu=neu_teilnehmer,
            ohne_kontext=not self.query_one("#disk-mit-kontext", Checkbox).value,
        ), ""

    def _seitenzeile(self, diskussion: Diskussion, teilnehmer: list[Teilnehmer]) -> str:
        if diskussion.format != "diskussion":
            return t("discussion.head_team", namen=", ".join(x.name for x in teilnehmer))
        return t(
            "discussion.head_sides",
            pro_pos=diskussion.position(PRO), contra_pos=diskussion.position(CONTRA),
            pro=", ".join(x.name for x in teilnehmer if x.seite == PRO),
            contra=", ".join(x.name for x in teilnehmer if x.seite == CONTRA),
        )

    def _pruefen(self) -> None:
        """Vorschau, Grund und Knopf auf den aktuellen Stand bringen."""
        auftrag, grund = self.auftrag()
        vorschau = ""
        if auftrag is not None:
            vorschau = self._seitenzeile(auftrag.diskussion,
                                         auftrag.diskussion.teilnehmer + auftrag.neu)
        self.query_one("#disk-vorschau", Static).update(Text(vorschau))
        self.query_one("#disk-grund", Static).update(Text(grund))
        self.query_one("#disk-starten", Button).disabled = auftrag is None
        # Eine Team-Diskussion kennt keine Seiten, also auch keine Positionen.
        mit_seiten = self.query_one("#disk-format", Select).value == "diskussion"
        self.query_one("#disk-positionen").display = mit_seiten
        self.query_one("#disk-positionen-hinweis").display = mit_seiten

    @on(Input.Changed)
    @on(TextArea.Changed)
    @on(Checkbox.Changed)
    @on(Select.Changed)
    def _geaendert(self) -> None:
        if not self.has_class("laeuft"):
            self._pruefen()

    # -- Knoepfe --------------------------------------------------------

    @on(Button.Pressed, "#disk-starten")
    def _knopf_starten(self) -> None:
        auftrag, grund = self.auftrag()
        if auftrag is None:
            self.notify(grund, severity="warning", markup=False)
            return
        self.post_message(self.Starten(auftrag))

    @on(Button.Pressed, "#disk-anhalten")
    def _knopf_anhalten(self) -> None:
        self.query_one("#disk-anhalten", Button).disabled = True
        self._zustand = t("discussion.state_stopping")
        self._kopf_zeichnen()
        self.post_message(self.Anhalten())

    def action_zur_uebersicht(self) -> None:
        if self.has_class("fertig"):
            self._knopf_neue()

    @on(Button.Pressed, "#disk-neue")
    def _knopf_neue(self) -> None:
        self.remove_class("fertig")
        self._diskussion = None
        self._pruefen()
        self.post_message(self.Kennzahlen())

    @on(Button.Pressed, "#disk-fortsetzen")
    def _knopf_fortsetzen(self) -> None:
        roh = self.query_one("#disk-weiter", Input).value.strip()
        if self._diskussion is None:
            return
        if not roh.isdigit() or not 1 <= int(roh) <= 50:
            self.notify(t("discussion.bad_more"), severity="warning", markup=False)
            return
        modell = str(self.query_one("#disk-weiter-modell", Select).value)
        hinweis = self.query_one("#disk-weiter-info", TextArea).text
        mit_kontext = self.query_one("#disk-weiter-kontext", Checkbox).value
        self.post_message(self.Fortsetzen(self._diskussion, int(roh), self._protokoll, modell,
                                          hinweis, mit_kontext))
        self.query_one("#disk-weiter-info", TextArea).text = ""

    def fortsetzen_vorbereiten(self) -> None:
        """Nach "Fortsetzen" im Kontextmenue: das Hinweisfeld bekommt den Fokus."""
        self.query_one("#disk-weiter-info", TextArea).focus()

    def vorlage(self, diskussion: Diskussion) -> None:
        """Uebernimmt Thema und Einstellungen einer alten Diskussion ins Formular."""
        self.remove_class("fertig")
        self._diskussion = None
        self.query_one("#disk-thema", TextArea).text = diskussion.thema
        self.query_one("#disk-position-pro", Input).value = diskussion.positionen[0]
        self.query_one("#disk-position-contra", Input).value = diskussion.positionen[1]
        self.query_one("#disk-format", Select).value = diskussion.format
        self.query_one("#disk-runden", Input).value = str(diskussion.runden)
        self.query_one("#disk-modell", Select).value = diskussion.modell
        self.query_one("#disk-recherche", Checkbox).value = diskussion.recherche
        self.query_one("#disk-mit-kontext", Checkbox).value = not diskussion.ohne_kontext
        self._pruefen()
        self.query_one("#disk-thema", TextArea).focus()
        self.post_message(self.Kennzahlen())

    def _steuerung_zeigen(self, *, laeuft: bool) -> None:
        """Anhalten waehrend der Diskussion, danach Fortsetzen und Neue Diskussion."""
        self.query_one("#disk-anhalten", Button).display = laeuft
        fortsetzbar = not laeuft and self._diskussion is not None and self._diskussion.kennung > 0
        for widget_id in ("#disk-fortsetzen", "#disk-weiter", "#disk-weiter-einheit",
                          "#disk-weiter-modell", "#disk-weiter-raum"):
            self.query_one(widget_id).display = fortsetzbar
        self.query_one("#disk-neue", Button).display = not laeuft

    # -- Statuszeile ----------------------------------------------------

    def kennzahlen(self) -> tuple[list[StatusItem], str] | None:
        """Was die Statuszeile im Reiter zeigt, dazu der Pfad des Protokolls.

        None, solange das Formular steht - dann bleiben die Bus-Kennzahlen.
        """
        d = self._diskussion
        if d is None or not (self.has_class("laeuft") or self.has_class("fertig")):
            return None
        laeuft = self.has_class("laeuft")
        runde = self._runde if laeuft else d.gespielte_runden
        posten = [StatusItem(t("discussion.stat_round"), f"{runde} / {d.runden}")]
        if laeuft and self._redner:
            posten.append(StatusItem(t("discussion.stat_speaker"), self._redner,
                                     value_style="bold yellow"))
        elif not laeuft:
            posten.append(StatusItem(t("discussion.stat_state"), t("discussion.stat_done")))
        namen = [x.name for x in d.teilnehmer] + [x.name for x in self._neu]
        posten.append(StatusItem(t("discussion.stat_agents"), ", ".join(namen)))
        posten.append(StatusItem(t("discussion.stat_model"), modell_name(d.modell)))
        beitraege = sum(1 for b in d.beitraege if b.art in ("beitrag", "schlusswort"))
        posten.append(StatusItem(t("discussion.stat_posts"), str(beitraege)))
        if d.beginn:
            posten.append(StatusItem(t("discussion.stat_since"), _datum(d.beginn)))
        v = self._verbrauch if self._verbrauch.gesamt else d.verbrauch
        posten.append(StatusItem(t("discussion.stat_tokens"), _tokens(v.echt)))
        posten.append(StatusItem(t("discussion.stat_cache"), _tokens(v.cache),
                                 value_style="dim"))
        return posten, self._protokoll

    def verbrauch(self, verbrauch: Verbrauch) -> None:
        """Neuer Stand des Verbrauchs, vom Ablauf nach jedem Beitrag."""
        self._verbrauch = verbrauch
        self.post_message(self.Kennzahlen())

    # -- Chat -----------------------------------------------------------

    def beginnen(self, diskussion: Diskussion, neu: list[Teilnehmer]) -> None:
        """Schaltet auf den Chat um. Die frischen Teilnehmer tragen noch Platzhalter.

        Steht schon etwas im Protokoll (Fortsetzen, Archiv), erscheint es sofort.
        """
        self._diskussion = diskussion
        self._neu = neu
        self._runde = diskussion.gespielte_runden
        self._redner = ""
        self._verbrauch = Verbrauch()
        # Das Protokoll kommt erst mit dem Ende - bis dahin kein Link, sonst
        # stuende hier der einer zuvor angesehenen Diskussion.
        self._protokoll = ""
        self._zustand = t("discussion.state_starting") if neu else ""
        self._laeufer = {}
        chat = self.query_one("#disk-chat", VerticalScroll)
        chat.remove_children()
        if diskussion.beitraege:
            chat.mount_all([self._blase(b) for b in diskussion.beitraege])
            chat.call_after_refresh(chat.scroll_end, animate=False)
        if neu:
            self._laeufer_an("start", _Laeuft(t("discussion.anim_starting")))
        self.query_one("#disk-zusammenfassung", Static).update("")
        self.query_one("#disk-zusammenfassung-raum").remove_class("da")
        self.query_one("#disk-anhalten", Button).disabled = False
        self.remove_class("fertig")
        self.add_class("laeuft")
        self._steuerung_zeigen(laeuft=True)
        self._kopf_zeichnen()
        self.post_message(self.Kennzahlen())

    def _kopf_zeichnen(self) -> None:
        d = self._diskussion
        if d is None:
            return
        teilnehmer = list(d.teilnehmer) + self._neu
        kopf = Text()
        kopf.append(d.thema, style="bold")
        kopf.append("\n")
        kopf.append(self._seitenzeile(d, teilnehmer))
        regeln = t("discussion.rules_research_on") if d.recherche else t(
            "discussion.rules_research_off")
        kopf.append(f"\n{regeln}", style="dim")
        modell = t("discussion.head_model", modell=modell_name(d.modell))
        echt = [f"{x.name}: {x.modell}" for x in d.teilnehmer if x.modell]
        if echt:
            modell = f"{modell} ({', '.join(echt)})"
        kopf.append(f"  ·  {modell}", style="dim")
        if self._zustand:
            kopf.append(f"\n{self._zustand}", style="italic")
        self.query_one("#disk-kopf", Static).update(kopf)

    # -- Animationen ----------------------------------------------------

    def _laeufer_an(self, schluessel: str, widget: _Laeuft) -> None:
        """Haengt eine laufende Anzeige an den Chat, eine je Schluessel."""
        self._laeufer_weg(schluessel)
        self._laeufer[schluessel] = widget
        chat = self.query_one("#disk-chat", VerticalScroll)
        chat.mount(widget)
        chat.scroll_end(animate=False)

    def _laeufer_weg(self, schluessel: str) -> _Laeuft | None:
        widget = self._laeufer.pop(schluessel, None)
        if widget is not None:
            widget.remove()
        return widget

    def vorbereitung_beginnt(self, teilnehmer: list[Teilnehmer]) -> None:
        """Die Recherche laeuft - je Teilnehmer eine Zeile mit Spinner und Uhr."""
        self._laeufer_weg("start")
        self._recherche_gesamt = len(teilnehmer)
        for x in teilnehmer:
            self._laeufer_an(f"recherche:{x.name}",
                             _Laeuft(t("discussion.anim_research", name=x.name)))
        self._zustand = t("discussion.state_research", fertig=0, gesamt=len(teilnehmer))
        self._kopf_zeichnen()

    def redner(self, name: str, runde: int) -> None:
        """Der Moderator gibt gerade jemandem das Wort."""
        if self._diskussion is None:
            return
        self._runde, self._redner = runde, name
        if not self.query_one("#disk-anhalten", Button).disabled:
            self._zustand = t("discussion.state_turn", runde=runde,
                              runden=self._diskussion.runden, name=name)
        self._kopf_zeichnen()
        seite = next((x.seite for x in self._diskussion.teilnehmer if x.name == name), "")
        if self._diskussion.format != "diskussion":
            seite = ""
        klasse = {PRO: "disk-pro", CONTRA: "disk-contra"}.get(seite, "disk-team")
        self._laeufer_an("tippt", _Laeuft(t("discussion.anim_typing", name=name), schreibt=True,
                                          classes=f"disk-tippt {klasse}"))
        self.post_message(self.Kennzahlen())

    def beitrag(self, beitrag: Beitrag) -> None:
        """Haengt einen Eintrag an den Chat. Er ersetzt die passende laufende Anzeige."""
        chat = self.query_one("#disk-chat", VerticalScroll)
        recherche = (self._laeufer.pop(f"recherche:{beitrag.name}", None)
                     if beitrag.runde == 0 else None)
        if recherche is not None:
            # An die Stelle der Recherchezeile, damit die Reihenfolge bleibt.
            chat.mount(self._blase(beitrag, _dauer(recherche.sekunden)), before=recherche)
            recherche.remove()
            offen = sum(1 for k in self._laeufer if k.startswith("recherche:"))
            self._zustand = t("discussion.state_research",
                              fertig=self._recherche_gesamt - offen, gesamt=self._recherche_gesamt)
            self._kopf_zeichnen()
        else:
            self._laeufer_weg("tippt")
            chat.mount(self._blase(beitrag))
            chat.scroll_end(animate=False)
        self.post_message(self.Kennzahlen())

    def _farben(self) -> dict[str, str]:
        """Die Farben der Seiten, wie die Raender der Blasen."""
        variablen = self.app.theme_variables
        return {PRO: variablen.get("primary", "blue"), CONTRA: variablen.get("accent", "magenta"),
                "": variablen.get("secondary", "cyan")}

    def _erwaehnungen(self, text: Text, sprecher: str) -> None:
        """Faerbt die Namen der ANDEREN Teilnehmer in der Farbe ihrer Seite."""
        d = self._diskussion
        if d is None:
            return
        farben = self._farben()
        for teilnehmer in d.teilnehmer:
            if teilnehmer.name.lower() == sprecher.lower() or not teilnehmer.name:
                continue
            seite = teilnehmer.seite if d.format == "diskussion" else ""
            stil = Style(bold=True, color=farben.get(seite, farben[""]))
            text.highlight_regex(rf"\b{re.escape(teilnehmer.name)}\b", stil)

    def _blase(self, beitrag: Beitrag, dauer: str = "") -> Static:
        d = self._diskussion
        if beitrag.art == "vorbereitung":
            # Die Notizen sind privat - im Chat steht nur, dass recherchiert wurde.
            text = (t("discussion.research_failed", name=beitrag.name)
                    if beitrag.ungeprueft else t("discussion.researched", name=beitrag.name))
            if dauer:
                text = f"{text} ({dauer})"
            return Static(Text(text), classes="disk-meldung")
        if beitrag.art == "moderator":
            inhalt = Text()
            inhalt.append(t("discussion.moderator_head", zeit=beitrag.zeit[:5]), style="bold")
            inhalt.append("\n")
            inhalt.append(beitrag.text)
            return Static(inhalt, classes="disk-moderator")
        if beitrag.art in ("fehler", "ausgelassen"):
            return Static(Text(f"{beitrag.name}: {beitrag.text}"), classes="disk-meldung")
        mit_seiten = d is not None and d.format == "diskussion" and beitrag.seite
        position = d.position(beitrag.seite) if (d is not None and mit_seiten) else ""
        kopf = t("discussion.bubble_head", name=beitrag.name, runde=beitrag.runde)
        if position:
            kopf = f"{kopf} · {position}"
        if beitrag.art == "schlusswort":
            kopf = f"{beitrag.name} · {t('discussion.head_closing')}"
        inhalt = Text()
        inhalt.append(kopf, style="bold")
        if beitrag.ungeprueft:
            inhalt.append(f"  {t('discussion.unverified')}", style="italic dim")
        inhalt.append("\n")
        # Leerzeile zwischen den Absaetzen: ein einfacher Umbruch ginge im
        # Zeilenumbruch einer breiten Blase unter.
        rumpf = Text("\n\n".join(absaetze(beitrag.text)))
        self._erwaehnungen(rumpf, beitrag.name)
        inhalt.append_text(rumpf)
        if beitrag.hinweis:
            inhalt.append(f"\n{beitrag.hinweis}", style="dim italic")
        seite = beitrag.seite if mit_seiten else "team"
        klasse = {PRO: "disk-pro", CONTRA: "disk-contra"}.get(seite, "disk-team")
        return Static(inhalt, classes=f"disk-blase {klasse}")

    def meldung(self, text: str) -> None:
        """Eine Zeile des Ablaufs (Start, Namen, Zusammenfassung wird erstellt)."""
        self._zustand = text
        self._kopf_zeichnen()
        if text == t("discussion.summary_pending"):
            self._laeufer_weg("tippt")
            self._laeufer_an("zusammenfassung", _Laeuft(text))

    def teilnehmer_bekannt(self, diskussion: Diskussion) -> None:
        """Die frischen Agenten haben ihre Namen - Kopf neu zeichnen."""
        self._diskussion = diskussion
        self._neu = []
        self._laeufer_weg("start")
        self._kopf_zeichnen()
        self.post_message(self.Kennzahlen())

    def fertig(self, diskussion: Diskussion, ende: str, protokoll: str) -> None:
        """Beendet: Zusammenfassung unter den Chat, Knoepfe zum Fortsetzen und fuer Neues."""
        self._diskussion = diskussion
        self._protokoll = protokoll
        self._redner = ""
        self._zustand = t("discussion.state_done_short", ende=ende) if ende else ""
        self._kopf_zeichnen()
        for schluessel in list(self._laeufer):
            self._laeufer_weg(schluessel)
        self.query_one("#disk-weiter-modell", Select).value = diskussion.modell
        self.query_one("#disk-weiter-kontext", Checkbox).value = not diskussion.ohne_kontext
        if diskussion.zusammenfassung:
            inhalt = Text()
            inhalt.append(t("discussion.summary_title"), style="bold")
            inhalt.append("\n")
            inhalt.append(diskussion.zusammenfassung)
            self.query_one("#disk-zusammenfassung", Static).update(inhalt)
            self.query_one("#disk-zusammenfassung-raum").add_class("da")
        self.remove_class("laeuft")
        self.add_class("fertig")
        self._steuerung_zeigen(laeuft=False)
        self.post_message(self.Kennzahlen())


def _datum(iso: str) -> str:
    """ISO-Zeitpunkt als ``28.09.2026 17:12``, Unlesbares unveraendert."""
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


def protokoll_name(pfad: str) -> str:
    """Der Dateiname eines Protokolls fuer die Anzeige."""
    return Path(pfad).name if pfad else ""
